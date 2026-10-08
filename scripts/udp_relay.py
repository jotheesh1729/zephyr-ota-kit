#!/usr/bin/env python3
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
"""Host side of the kit's dial-out transport (CONFIG_OTA_KIT_WIFI_DIAL).

The device opens a UDP socket to this host and sends a hello until it gets an answer. This
relay learns the device's address from that, and passes SMP datagrams between the device and
a local SMP client. With it the normal tools work unchanged:

    scripts/udp_relay.py &
    scripts/ota_update.py IMAGE --udp 127.0.0.1 --port /dev/ttyACM0

No encryption and no authentication: the relay talks to whoever sent the last hello.

Usage: scripts/udp_relay.py [--device-port 1338] [--client-port 1337]
"""
import argparse
import selectors
import socket
import time

HELLO = b"ota-kit-hello"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--device-port", type=int, default=1338, help="port the device dials")
    p.add_argument("--client-port", type=int, default=1337, help="local port for the SMP client")
    a = p.parse_args()
    dev = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dev.bind(("0.0.0.0", a.device_port))
    cli = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    cli.bind(("127.0.0.1", a.client_port))
    sel = selectors.DefaultSelector()
    sel.register(dev, selectors.EVENT_READ)
    sel.register(cli, selectors.EVENT_READ)
    device = client = None
    print(f"relay: device port {a.device_port}, client port 127.0.0.1:{a.client_port}", flush=True)
    while True:
        for key, _ in sel.select():
            try:
                data, addr = key.fileobj.recvfrom(4096)
                if key.fileobj is dev:
                    if addr != device:
                        device = addr
                        print(f"[{time.strftime('%H:%M:%S')}] relay: device seen", flush=True)
                    if data != HELLO and client:
                        cli.sendto(data, client)
                else:
                    client = addr
                    if device:
                        dev.sendto(data, device)  # no device yet: dropped, the client asks again
            except OSError as e:  # the host's network went away for a moment: the datagram is lost
                print(f"[{time.strftime('%H:%M:%S')}] relay: {type(e).__name__}: {e}", flush=True)


if __name__ == "__main__":
    main()
