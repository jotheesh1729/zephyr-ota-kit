#!/usr/bin/env python3
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
"""Switch the test board's power through the relay controller (tools/relay_controller).

Usage as a tool:   scripts/powerctl.py on | off | state | cycle [OFF_MS] | install
Usage as a module: with PowerCtl() as p: p.on(); p.cycle(2000)

"on" closes the relay, which powers the board. Leaving the `with` block opens the relay,
unless keep=True was given. Every command is logged with its send time and the time its
reply arrived, on the host's monotonic clock. Those times are host side: they include the
USB serial link, and not the relay itself, which needs a few more milliseconds to move and
bounces when it does.
"""
import glob
import sys
import time
from pathlib import Path

import serial

BY_ID = "/dev/serial/by-id/usb-Silicon_Labs_CP2102*"


def find_port():
    ports = glob.glob(BY_ID)
    if len(ports) != 1:
        raise SystemExit(f"expected one relay controller at {BY_ID}, found {len(ports)}")
    return ports[0]


class PowerCtl:
    def __init__(self, port=None, keep=False):
        self.keep = keep
        self.log = []  # (command, t_send, t_ack, reply)
        self.s = serial.Serial(port or find_port(), 115200, timeout=2)
        # Opening the port can reset the ESP32, which opens the relay. Wait until it answers.
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.s.reset_input_buffer()
            self.s.write(b"STATE\n")
            if self.s.readline().strip() in (b"OK ON", b"OK OFF"):
                return
        raise SystemExit("relay controller does not answer, is tools/relay_controller/main.py installed?")

    def cmd(self, text, timeout=2.0):
        self.s.timeout = timeout
        self.s.reset_input_buffer()
        t_send = time.monotonic()
        self.s.write(text.encode() + b"\n")
        self.s.flush()
        reply = self.s.readline().strip().decode(errors="replace")
        t_ack = time.monotonic()
        self.log.append((text, t_send, t_ack, reply))
        if not reply.startswith("OK"):
            raise RuntimeError(f"relay controller answered {reply!r} to {text!r}")
        return reply

    def on(self):
        self.cmd("ON")

    def off(self):
        self.cmd("OFF")

    def state(self):
        return self.cmd("STATE").endswith("ON")

    def cycle(self, off_ms=2000):
        """Cut the power for off_ms. Timed on the host, so that both edges are in the log."""
        self.off()
        time.sleep(off_ms / 1000)
        self.on()

    def close(self):
        try:
            if not self.keep:
                self.off()
        finally:
            self.s.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def install(port):
    """Copy tools/relay_controller/main.py to the ESP32 over the MicroPython raw REPL."""
    code = (Path(__file__).resolve().parent.parent / "tools/relay_controller/main.py").read_text()
    with serial.Serial(port, 115200, timeout=1) as s:
        s.write(b"EXIT\n")           # in case the controller is already running
        time.sleep(0.5)
        s.write(b"\r\x03\x03")       # stop anything else
        time.sleep(0.3)
        s.write(b"\x01")             # raw REPL
        time.sleep(0.3)
        s.reset_input_buffer()
        s.write(f"f=open('main.py','w');f.write({code!r});f.close()\n".encode() + b"\x04")
        time.sleep(1.5)
        reply = s.read(200)
        if not reply.startswith(b"OK") or b"Traceback" in reply:
            raise SystemExit(f"upload failed: {reply!r}")
        s.write(b"\x02")             # back to the normal prompt
        s.write(b"import machine; machine.reset()\r\n")
    print("installed, the controller starts with the relay open")


if __name__ == "__main__":
    args = sys.argv[1:] or ["state"]
    if args[0] == "install":
        install(find_port())
    else:
        with PowerCtl(keep=True) as p:  # a command line "on" has to outlive this process
            if args[0] == "on":
                p.on()
            elif args[0] == "off":
                p.off()
            elif args[0] == "cycle":
                p.cycle(int(args[1]) if len(args) > 1 else 2000)
            elif args[0] != "state":
                raise SystemExit(__doc__)
            print("relay closed, board powered" if p.state() else "relay open, board off")
