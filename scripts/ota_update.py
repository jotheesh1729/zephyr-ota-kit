#!/usr/bin/env python3
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
"""OTA update over SMP: upload, mark for test, reset, wait for self confirm.

Usage: scripts/ota_update.py build/v1.1.0/app/zephyr/zephyr.signed.bin [--port /dev/ttyACM0]
       scripts/ota_update.py build/ble-v1.1.0/app/zephyr/zephyr.signed.bin --ble ota-kit
SMP runs over the UART, or over BLE with --ble. The boot log is always read from the UART.
Needs: source ~/zephyrproject/.venv/bin/activate
"""
import argparse
import asyncio
import contextlib
import sys
import time

import serial
from smpclient import SMPClient
from smpclient.generics import error, success
from smpclient.requests.image_management import ImageStatesRead, ImageStatesWrite
from smpclient.requests.os_management import ResetWrite
from smpclient.transport.serial import SMPSerialTransport

CONFIRM_LINE = "image confirmed"
BOOT_TIMEOUT_S = 120  # swap + boot + health check window


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def udp_transport():
    """SMP UDP transport that drops every answer that is not for the request just sent.

    UDP may deliver a datagram twice or late. smpclient 7.3.0 stops with SMPBadSequence when
    that happens (seen on the first Wi-Fi upload). Byte 6 of an SMP header is the sequence number.
    """
    from smpclient.transport.udp import SMPUDPTransport

    class DropStale(SMPUDPTransport):
        expected = None

        async def send(self, data):
            self.expected = data[6]
            await super().send(data)

        async def receive(self):
            while True:
                frame = await super().receive()
                if frame[6] == self.expected:
                    return frame
                log(f"  host: DUPLICATE or late UDP answer dropped, sequence {frame[6]}")

    return DropStale()


async def wait_reachable(client, seconds=40.0):
    """UDP: ask for the image state until the board answers. After a reset it first has to
    join the Wi-Fi network, and a request sent before that is lost."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            await client.request(ImageStatesRead(), timeout_s=2.0)
            return
        except TimeoutError:
            if time.monotonic() > deadline:
                raise
            log("  host: no answer over UDP yet, asking again")


@contextlib.asynccontextmanager
async def session(target):
    """SMP session. `target` is a serial port, "ble:<device name>" or "udp:<IPv4 address>"."""
    if target.startswith("udp:"):
        # After a reset the board has to join the Wi-Fi network again before it answers.
        client, connect_s, tries = SMPClient(udp_transport(), target[4:]), 5.0, 8
    elif target.startswith("ble:"):
        from smpclient.transport.ble import SMPBLETransport  # needs bleak, only for BLE
        client, connect_s, tries = SMPClient(SMPBLETransport(), target[4:]), 20.0, 3
    else:
        client, connect_s, tries = SMPClient(SMPSerialTransport(), target), 5.0, 1
    for attempt in range(1, tries + 1):
        try:
            await client.connect(connect_s)
            break
        except Exception as e:  # BLE connects fail now and then, UDP until the board has joined
            if attempt == tries:
                raise
            log(f"  host: connect attempt {attempt} failed ({type(e).__name__}), retrying")
            await asyncio.sleep(2)
    try:
        if target.startswith("udp:"):
            await wait_reachable(client)
        yield client
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()


async def smp(client, request, timeout_s=10.0):
    rsp = await client.request(request, timeout_s=timeout_s)
    if error(rsp):
        raise RuntimeError(f"{type(request).__name__} failed: {rsp}")
    assert success(rsp)
    return rsp


async def read_slots(target):
    async with session(target) as client:
        return (await smp(client, ImageStatesRead())).images


def fmt(images):
    return ", ".join(
        f"slot{i.slot} v{i.version}"
        + "".join(f" {f}" for f in ("active", "confirmed", "pending") if getattr(i, f))
        for i in images
    )


async def upload_and_reset(target, image):
    """Returns upload time in seconds."""
    async with session(target) as client:
        log(f"before: {fmt((await smp(client, ImageStatesRead())).images)}")

        t0 = time.monotonic()
        # The first request erases slot 1 on the QSPI flash, so give it time.
        async for offset in client.upload(image, first_timeout_s=120.0,
                                          subsequent_timeout_s=20.0):
            print(f"\r  uploaded {offset}/{len(image)} B", end="", flush=True)
        upload_s = time.monotonic() - t0
        print()
        log(f"upload done in {upload_s:.2f} s ({len(image) / upload_s:.0f} B/s)")

        images = (await smp(client, ImageStatesRead())).images
        new = next(i for i in images if i.slot == 1)
        # confirm=False is "test": MCUboot swaps once, and reverts unless the app confirms.
        await smp(client, ImageStatesWrite(hash=new.hash, confirm=False))
        log(f"slot 1 v{new.version} marked for test")

        await smp(client, ResetWrite())
        log("reset sent")
    return upload_s


# The last one appears when a hung image was reset by the watchdog and the old one is back.
STOP_LINES = (CONFIRM_LINE, "health check FAILED", "confirm write FAILED",
              "last reset by WATCHDOG")


def watch_boot(port, stop=STOP_LINES, timeout_s=BOOT_TIMEOUT_S, trigger=None):
    """Read the console until a line contains one of `stop`.

    `trigger` runs once the port is open, for resets that would otherwise race the reader.
    Returns (lines, swap_s) where swap_s is MCUboot start to app jump.
    """
    lines, t_boot, swap_s, same = [], None, None, 1
    with serial.Serial(port, 115200, timeout=0.2) as s:
        if trigger:
            trigger()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            raw = s.readline()
            if not raw.endswith(b"\n"):
                continue
            line = raw.decode(errors="replace").strip()
            now = time.monotonic()
            # The same line many times in a row was seen on an ESP32 dev board, say so once.
            same = same + 1 if lines and line == lines[-1] and line else 1
            if same == 6:
                log(f"  host: REPEAT, console line received more than 5 times in a row: {line[:60]!r}")
            lines.append(line)
            log(f"  board: {line}")
            if "Starting bootloader" in line:
                t_boot = now
            elif "Jumping to the first image slot" in line and t_boot and swap_s is None:
                swap_s = now - t_boot  # MCUboot run time, includes the swap
            if any(x in line for x in stop):
                break
    return lines, swap_s


def run(target, path, console="/dev/ttyACM0"):
    """Full update. Returns a dict of results, used by the test and measurement scripts."""
    image = open(path, "rb").read()
    log(f"image {path}, {len(image)} B")

    t_start = time.monotonic()
    upload_s = asyncio.run(upload_and_reset(target, image))
    lines, swap_s = watch_boot(console)
    confirmed = any(CONFIRM_LINE in line for line in lines)
    total_s = time.monotonic() - t_start

    images = asyncio.run(read_slots(target))
    log(f"after:  {fmt(images)}")
    running = next(i for i in images if i.slot == 0)
    ok = confirmed and running.confirmed
    reverted = any("Swap type: revert" in line for line in lines)

    log(f"RESULT {'OK' if ok else 'ROLLED BACK' if reverted else 'FAIL'}: "
        f"running v{running.version}, "
        f"upload {upload_s:.2f} s, "
        f"bootloader+swap {f'{swap_s:.2f} s' if swap_s is not None else 'n/a'}, "
        f"total {total_s:.2f} s")
    return {"ok": ok, "version": running.version, "image_bytes": len(image),
            "upload_s": upload_s, "swap_s": swap_s, "total_s": total_s}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image")
    ap.add_argument("--port", default="/dev/ttyACM0",
                    help="UART: console, and SMP unless --ble or --udp")
    ap.add_argument("--ble", metavar="NAME", help="run SMP over BLE to the device with this name")
    ap.add_argument("--udp", metavar="IP", help="run SMP over UDP to this address (Wi-Fi)")
    args = ap.parse_args()
    target = f"udp:{args.udp}" if args.udp else f"ble:{args.ble}" if args.ble else args.port
    sys.exit(0 if run(target, args.image, console=args.port)["ok"] else 1)
