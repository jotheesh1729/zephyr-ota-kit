/*
 * Copyright (c) 2026 Jotheesh Kummathi
 * SPDX-License-Identifier: Apache-2.0
 *
 * OTA kit, Wi-Fi part: join a stored network, so that Zephyr's SMP UDP transport is reachable.
 *
 * The network name and passphrase are not in the build. They are stored on the board with
 * Zephyr's wifi_credentials library, by the shell command "wifi cred add" sent over SMP on the
 * UART (scripts/wifi_provision.py). A board that boots with a stored network refuses SMP shell
 * commands, so that nobody on that network can run them.
 */
#include <zephyr/kernel.h>
#include <zephyr/net/net_if.h>
#include <zephyr/net/net_ip.h>
#include <zephyr/net/net_mgmt.h>
#include <zephyr/net/net_event.h>
#include <zephyr/net/wifi_mgmt.h>
#include <zephyr/net/wifi_credentials.h>
#include <zephyr/mgmt/mcumgr/mgmt/mgmt.h>
#include <zephyr/mgmt/mcumgr/mgmt/callbacks.h>

static struct net_mgmt_event_callback ip_cb;

/*
 * Workaround for an open defect, docs/BOARD_ESP32.md "Early boot abort": on the ESP32 this
 * file without the word below gave an image that aborts before main() with "Failed to init
 * flash chip: 1". One more data word moved the link layout and the image booted. Why is not known.
 */
#if CONFIG_OTA_KIT_WIFI_LAYOUT_PAD_WORDS > 0
volatile uint32_t ota_kit_wifi_layout_pad[CONFIG_OTA_KIT_WIFI_LAYOUT_PAD_WORDS] = { 1 };
#endif

static void on_ip(struct net_mgmt_event_callback *cb, uint64_t event, struct net_if *iface)
{
	char ip[NET_IPV4_ADDR_LEN];

	ARG_UNUSED(cb);

	if (event == NET_EVENT_IPV4_DHCP_BOUND) {
		printk("WIFI: joined, IP %s, %u ms after boot\n",
		       net_addr_ntop(AF_INET, &iface->config.dhcpv4.requested_ip, ip, sizeof(ip)),
		       k_uptime_get_32());
	}
}

/* Set at boot. SMP shell commands exist only to store the first network. */
static bool shell_locked;

static enum mgmt_cb_return shell_lock(uint32_t event, enum mgmt_cb_return prev_status,
				      int32_t *rc, uint16_t *group, bool *abort_more,
				      void *data, size_t data_size)
{
	const struct mgmt_evt_op_cmd_arg *cmd = data;

	ARG_UNUSED(event);
	ARG_UNUSED(prev_status);
	ARG_UNUSED(group);
	ARG_UNUSED(abort_more);
	ARG_UNUSED(data_size);

	if ((cmd->group == MGMT_GROUP_ID_SHELL) && shell_locked) {
		*rc = MGMT_ERR_EACCESSDENIED;
		return MGMT_CB_ERROR_RC;
	}
	return MGMT_CB_OK;
}

static struct mgmt_callback shell_lock_cb = {
	.callback = shell_lock,
	.event_id = MGMT_EVT_OP_CMD_RECV,
};

static void wifi_thread(void *a, void *b, void *c)
{
	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);

#if CONFIG_OTA_KIT_WIFI_LAYOUT_PAD_WORDS > 0
	(void)ota_kit_wifi_layout_pad[0]; /* keeps the array in the image */
#endif
	shell_locked = !wifi_credentials_is_empty();
	mgmt_callback_register(&shell_lock_cb);
	net_mgmt_init_event_callback(&ip_cb, on_ip, NET_EVENT_IPV4_DHCP_BOUND);
	net_mgmt_add_event_callback(&ip_cb);

	if (!shell_locked) {
		printk("WIFI: no stored network\n");
		return;
	}
	printk("WIFI: stored network found, connecting\n");
	/* ponytail: fixed wait for the Wi-Fi driver, use the interface up event if this is too short */
	k_sleep(K_MSEC(CONFIG_OTA_KIT_WIFI_START_DELAY_MS));
	int rc = net_mgmt(NET_REQUEST_WIFI_CONNECT_STORED, net_if_get_default(), NULL, 0);

	if (rc != 0) {
		printk("WIFI: connect request failed %d\n", rc);
	}
}

K_THREAD_DEFINE(ota_kit_wifi, 4096, wifi_thread, NULL, NULL, NULL, K_LOWEST_APPLICATION_THREAD_PRIO,
		0, 0);
