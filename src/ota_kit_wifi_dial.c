/*
 * Copyright (c) 2026 Jotheesh Kummathi
 * SPDX-License-Identifier: Apache-2.0
 *
 * OTA kit, SMP transport for Wi-Fi drivers that cannot do sendto() and recvfrom() with an
 * address, such as the eS-WiFi offload driver. Zephyr's SMP UDP transport needs both.
 *
 * The device opens a UDP socket and connects it to a host. From then on it only uses send()
 * and recv(). It sends a short hello until the host answers, so that the host learns where
 * the device is. scripts/udp_relay.py is the host side.
 */
#include <errno.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/net/net_if.h>
#include <zephyr/net/net_ip.h>
#include <zephyr/net/socket.h>
#include <zephyr/net_buf.h>
#include <zephyr/mgmt/mcumgr/mgmt/mgmt.h>
#include <zephyr/mgmt/mcumgr/transport/smp.h>
#include <mgmt/mcumgr/transport/smp_internal.h>

#define HELLO "ota-kit-hello"

static struct smp_transport dial_transport;
static int sock = -1;
#define SMP_HDR 8U

static uint8_t rx[CONFIG_OTA_KIT_WIFI_DIAL_MTU];
static size_t have;     /* bytes of a request collected so far */
static int64_t started; /* when its first bytes arrived */
static int64_t last_rx; /* when anything arrived, or the last hello was sent */

static int dial_tx(struct net_buf *nb)
{
	int rc = zsock_send(sock, nb->data, nb->len, 0);

	smp_packet_free(nb);
	return (rc < 0) ? MGMT_ERR_EINVAL : MGMT_ERR_EOK;
}

static uint16_t dial_mtu(const struct net_buf *nb)
{
	ARG_UNUSED(nb);
	return CONFIG_OTA_KIT_WIFI_DIAL_MTU;
}

static bool have_address(void)
{
	struct net_if *iface = net_if_get_default();

	return (iface != NULL) &&
	       (net_if_ipv4_get_global_addr(iface, NET_ADDR_PREFERRED) != NULL);
}

#ifdef CONFIG_OTA_KIT_WIFI_DIAL_PROBE
/* One connected socket to an echo server on port + 1: connect, send, recv, with no address. */
static void probe(const struct net_sockaddr_in *host, int type, int proto, const char *name)
{
	struct net_sockaddr_in to = *host;
	char buf[16] = "probe";
	int s = zsock_socket(NET_AF_INET, type, proto);
	int c, tx, rx_len;

	to.sin_port = net_htons(CONFIG_OTA_KIT_WIFI_DIAL_PORT + 1);
	c = zsock_connect(s, (struct net_sockaddr *)&to, sizeof(to));
	tx = zsock_send(s, buf, 5, 0);
	rx_len = zsock_recv(s, buf, sizeof(buf), 0);
	printk("WIFI: probe %s: socket %d, connect %d, send %d, recv %d, errno %d\n", name, s, c, tx,
	       rx_len, errno);
	(void)zsock_close(s);
}
#endif

static void dial_thread(void *a, void *b, void *c)
{
	struct net_sockaddr_in host = {
		.sin_family = NET_AF_INET,
		.sin_port = net_htons(CONFIG_OTA_KIT_WIFI_DIAL_PORT),
	};

	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);

	dial_transport.functions.output = dial_tx;
	dial_transport.functions.get_mtu = dial_mtu;
	if (smp_transport_init(&dial_transport) != 0) {
		printk("WIFI: SMP transport init failed\n");
		return;
	}
	if (zsock_inet_pton(NET_AF_INET, CONFIG_OTA_KIT_WIFI_DIAL_HOST, &host.sin_addr) != 1) {
		printk("WIFI: no valid host address in CONFIG_OTA_KIT_WIFI_DIAL_HOST\n");
		return;
	}
	while (!have_address()) {
		k_sleep(K_MSEC(500));
	}

#ifdef CONFIG_OTA_KIT_WIFI_DIAL_PROBE
	probe(&host, NET_SOCK_STREAM, NET_IPPROTO_TCP, "TCP");
	probe(&host, NET_SOCK_DGRAM, NET_IPPROTO_UDP, "UDP");
#endif

	sock = zsock_socket(NET_AF_INET, NET_SOCK_DGRAM, NET_IPPROTO_UDP);
	if ((sock < 0) ||
	    (zsock_connect(sock, (struct net_sockaddr *)&host, sizeof(host)) != 0)) {
		printk("WIFI: socket or connect failed, errno %d\n", errno);
		return;
	}
	printk("WIFI: dialing the host, UDP port %d\n", CONFIG_OTA_KIT_WIFI_DIAL_PORT);

	for (;;) {
		struct zsock_pollfd fd = { .fd = sock, .events = ZSOCK_POLLIN };
		size_t need;
		int len;

		/*
		 * Short waits, and a read after each one. The eS-WiFi driver only fetches data
		 * from the module when it is asked to, and its poll() returns -1 with ETIMEDOUT
		 * where others return 0. A long wait here left requests unanswered for its
		 * whole length (measured: 2 s stalls with a 2 s wait).
		 */
		(void)zsock_poll(&fd, 1, CONFIG_OTA_KIT_WIFI_DIAL_POLL_MS);
		len = zsock_recv(sock, &rx[have], sizeof(rx) - have, ZSOCK_MSG_DONTWAIT);
		if (len <= 0) {
			if ((have > 0) &&
			    ((k_uptime_get() - started) > CONFIG_OTA_KIT_WIFI_DIAL_REQUEST_MS)) {
				have = 0; /* the rest of that request did not come */
			}
			if ((k_uptime_get() - last_rx) > CONFIG_OTA_KIT_WIFI_DIAL_HELLO_MS) {
				last_rx = k_uptime_get();
				(void)zsock_send(sock, HELLO, sizeof(HELLO) - 1, 0);
			}
			continue;
		}
		last_rx = k_uptime_get();
		if (have == 0) {
			started = last_rx;
		}
		have += len;

		/*
		 * The eS-WiFi module can deliver one datagram in several pieces. An SMP packet
		 * says how long it is: 8 header bytes, payload length in bytes 2 and 3.
		 */
		while (have >= SMP_HDR) {
			struct net_buf *nb;

			need = SMP_HDR + (((size_t)rx[2] << 8) | rx[3]);
			if (need > sizeof(rx)) {
				have = 0; /* cannot be a request for this transport */
				break;
			}
			if (have < need) {
				break;
			}
			nb = smp_packet_alloc();
			if ((nb != NULL) && (need <= net_buf_tailroom(nb))) {
				net_buf_add_mem(nb, rx, need);
				smp_rx_req(&dial_transport, nb);
			} else if (nb != NULL) {
				smp_packet_free(nb);
			} else {
				/* no buffer: dropped, the host asks again or gives up */
			}
			have -= need;
			memmove(rx, &rx[need], have);
		}
	}
}

K_THREAD_DEFINE(ota_kit_wifi_dial, CONFIG_OTA_KIT_WIFI_DIAL_STACK_SIZE, dial_thread, NULL, NULL, NULL,
		K_LOWEST_APPLICATION_THREAD_PRIO, 0, 0);
