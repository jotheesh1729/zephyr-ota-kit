#!/usr/bin/env python3
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
"""Repeat "erase slot 1, upload" over SMP on a UART and record every request that gets no answer or a damaged one.

No reset and no swap: the board keeps running the same image. One CSV row per upload.
Usage: tests/uart_soak.py PORT IMAGE COUNT OUT.csv [--baud N] [--frame N] [--lines-low] [--settle S]
  --frame      largest encoded SMP frame the host sends, smaller means smaller upload chunks
  --lines-low  open the port with DTR and RTS released and wait for the app banner before the
               first request of each upload. On an ESP32 dev board that open resets the chip.
  --settle     with --lines-low: seconds to wait after the app banner

Also counts identical console lines in a row, see repeats().
"""
import argparse
import asyncio
import csv
import logging
import re
import time

import serial
from smpclient import SMPClient
from smpclient.requests.image_management import ImageErase, ImageStatesRead
from smpclient.transport.serial import SMPSerialTransport

TIMEOUT_S = 10.0  # an answer normally comes within 0.1 s
BANNER = b"OTA app v"


def repeats(text, more_than=5):
    """[(line, count)] for every run of more than `more_than` identical non-empty lines."""
    out, prev, n = [], None, 0
    for line in text.splitlines() + [None]:
        if line == prev:
            n += 1
            continue
        if prev and n > more_than:
            out.append((prev, n))
        prev, n = line, 1
    return out


def open_low(a):
    """Port with DTR and RTS released. Reads until the app banner, returns (port, text read)."""
    s = serial.Serial(baudrate=a.baud, timeout=0.05)
    s.dtr = False
    s.rts = False
    s.port = a.port
    s.open()
    buf, deadline = b"", time.monotonic() + 5
    while BANNER not in buf and time.monotonic() < deadline:
        buf += s.read(4096)
    deadline = time.monotonic() + max(a.settle, 0.05)  # at least the rest of the banner line
    while time.monotonic() < deadline:
        buf += s.read(4096)
    return s, buf.decode(errors="replace")


def stamp():
    return time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"


async def one(a, image):
    """Returns (step that failed or "", offset reached, error text)."""
    kw = {"max_smp_encoded_frame_size": a.frame} if a.frame else {}
    transport = SMPSerialTransport(baudrate=a.baud, **kw)
    if a.lines_low:  # keep the lines where open_low() left them, or this open resets the board
        transport._conn.dtr = False
        transport._conn.rts = False
    client = SMPClient(transport, a.port)
    step, offset = "connect", 0
    try:
        await client.connect(5.0)  # sends one request, to read the buffer sizes of the board
        step = "erase"
        await client.request(ImageErase(), timeout_s=TIMEOUT_S)
        step = "upload"
        async for offset in client.upload(image, first_timeout_s=TIMEOUT_S,
                                          subsequent_timeout_s=TIMEOUT_S):
            pass
        step = "state"
        await client.request(ImageStatesRead(), timeout_s=TIMEOUT_S)
        return "", offset, ""
    except Exception as e:  # no answer (TimeoutError) or a damaged one (SMPBadCRC and others)
        # a timeout message names the request: operation, group, command, sequence number
        text = " ".join(re.sub(r"smp_data=.*", "", str(e)).split())
        return step, offset, f"{type(e).__name__}: {text}"
    finally:
        await client.disconnect()


def console(a, seconds, held=None):
    """Whatever the board sends in `seconds`, as text. `held`: an open port to read from instead."""
    s = held or serial.Serial(a.port, a.baud, timeout=0.05)
    buf, deadline = b"", time.monotonic() + seconds
    while time.monotonic() < deadline:
        buf += s.read(65536)
    s.close()
    return buf.decode(errors="replace").strip()


class ParamTimeouts(logging.Handler):
    """smpclient only logs it when its first request, for the buffer sizes, gets no answer."""
    count = 0

    def emit(self, record):
        ParamTimeouts.count += "MCUMgr parameters" in record.getMessage()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("port")
    p.add_argument("image")
    p.add_argument("count", type=int)
    p.add_argument("out")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--frame", type=int)
    p.add_argument("--lines-low", action="store_true")
    p.add_argument("--settle", type=float, default=0.0)
    a = p.parse_args()
    image = open(a.image, "rb").read()
    logging.getLogger().addHandler(ParamTimeouts())
    failed = 0
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n", "time", "ok", "seconds", "failed_step", "offset", "request", "console_after",
                    "banner_seen", "repeated_lines", "first_request_unanswered"])
        for n in range(1, a.count + 1):
            t0, when, before = time.monotonic(), stamp(), ParamTimeouts.count
            held, boot = open_low(a) if a.lines_low else (None, "")
            step, offset, err = asyncio.run(one(a, image))
            # after a failure 2 s of console, else a short look, which is all the detector gets
            after = console(a, 2.0 if step else 0.3, held)
            runs = [(where, line, cnt) for where, text in (("before the first request", boot),
                                                           (f"after {step or 'the upload'}", after))
                    for line, cnt in repeats(text)]
            for where, line, cnt in runs:
                print(f"[{stamp()}] REPEAT upload {n}, {where}: {cnt} x {line[:60]!r}", flush=True)
            failed += bool(step)
            w.writerow([n, when, int(not step), f"{time.monotonic() - t0:.2f}", step, offset, err,
                        after[:4096] if step else "", int(BANNER.decode() in boot) if held else "",
                        "; ".join(f"{cnt} x {line[:40]} ({where})" for where, line, cnt in runs),
                        ParamTimeouts.count - before])
            f.flush()
            print(f"[{stamp()}] {n}/{a.count} {'FAIL ' + step + ' at ' + str(offset) if step else 'ok'}"
                  f" {time.monotonic() - t0:.1f} s {err[:200]}", flush=True)
            if step and after:
                print(f"  console after: {after!r}", flush=True)
    print(f"{a.count - failed} of {a.count} uploads complete, {failed} with a failed request")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
