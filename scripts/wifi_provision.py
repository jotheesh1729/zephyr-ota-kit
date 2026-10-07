#!/usr/bin/env python3
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
"""Store a Wi-Fi network on a board built with the ota-kit-wifi snippet, over SMP on the UART.

The network name and passphrase come from the environment variables OTA_WIFI_SSID and
OTA_WIFI_PSK, or from two prompts that do not echo. They are sent to the board and stored
there (Zephyr wifi_credentials). This script writes them nowhere and prints neither.
WPA2-PSK only. The board is then reset. From that boot on it joins the network and refuses
SMP shell commands, erase its flash to store another network.

Usage: scripts/wifi_provision.py [--port /dev/ttyUSB0]
"""
import argparse
import asyncio
import getpass
import logging
import os
import sys
import time

import serial
from smpclient import SMPClient
from smpclient.requests.os_management import ResetWrite
from smpclient.requests.shell_management import Execute
from smpclient.transport.serial import SMPSerialTransport

logging.disable(logging.CRITICAL)  # smpclient logs a failed request with its arguments


async def store_and_reset(port, command):
    # The first request after esptool has flashed the board fails with a CRC error (seen 3 of 3
    # times on an ESP32 dev board, the second request works). Nothing is sent before the connect
    # has worked, so trying it again is safe.
    for attempt in (1, 2, 3):
        client = SMPClient(SMPSerialTransport(), port)
        try:
            await client.connect(5.0)
            break
        except Exception:
            await client.disconnect()
            if attempt == 3:
                raise
    try:
        ret = getattr(await client.request(Execute(argv=command), timeout_s=15.0), "ret", None)
        if ret == 0:
            await client.request(ResetWrite(), timeout_s=5.0)
        return ret
    finally:
        await client.disconnect()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", default="/dev/ttyUSB0")
    port = p.parse_args().port
    ssid = os.environ.get("OTA_WIFI_SSID") or getpass.getpass("Network name (not shown): ")
    psk = os.environ.get("OTA_WIFI_PSK") or getpass.getpass("Passphrase (not shown): ")
    try:
        ret = asyncio.run(store_and_reset(
            port, ["wifi", "cred", "add", "-s", ssid, "-p", psk, "-k", "1"]))
    except Exception as e:  # the message of a failed request holds the arguments, do not print it
        print(f"FAILED: {type(e).__name__}. Is a network already stored, or the port busy?")
        return 1
    finally:
        del ssid, psk
    if ret != 0:
        print(f"FAILED: the board did not store the network, return code {ret}. "
              "Is one already stored?")
        return 1
    print("stored, board reset, waiting for it to join")
    with serial.Serial(port, 115200, timeout=0.5) as s:  # wait for the board to say it joined
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            line = s.readline().decode(errors="replace").strip()
            if line.startswith(("WIFI: joined", "WIFI: connect request")):
                print(line)
                return 0
    print("no join line from the board in 40 s")
    return 1


if __name__ == "__main__":
    sys.exit(main())
