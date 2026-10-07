# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
#
# Relay controller for the power loss tests. MicroPython on an ESP32, see docs/POWERLOSS.md.
#
# GPIO26 drives the relay input. High = relay closed = test board powered.
# The relay is open after boot, after any error, and after DEADMAN_S without a command.
#
# Serial protocol on the USB UART, 115200 baud, one command per line, one reply per command:
#   ON            close the relay          -> OK
#   OFF           open the relay           -> OK
#   PULSE <ms>    open for <ms>, then close (a power cut of that length) -> OK when done
#   STATE         -> OK ON   or   OK OFF
#   EXIT          open the relay and go back to the MicroPython prompt  -> OK
# Anything else -> ERR
import sys
import time

import micropython
import select
from machine import Pin

DEADMAN_S = 900  # a crashed host must not leave the board powered for ever

relay = Pin(26, Pin.OUT, value=0)


def main():
    micropython.kbd_intr(-1)  # the host may send any byte, 0x03 must not stop this script
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    last = time.ticks_ms()
    print("READY")
    try:
        while True:
            if not poll.poll(200):
                if relay.value() and time.ticks_diff(time.ticks_ms(), last) > DEADMAN_S * 1000:
                    relay.value(0)
                    print("DEADMAN OFF")
                continue
            words = sys.stdin.readline().strip().upper().split()
            last = time.ticks_ms()
            if words == ["ON"]:
                relay.value(1)
                print("OK")
            elif words == ["OFF"]:
                relay.value(0)
                print("OK")
            elif len(words) == 2 and words[0] == "PULSE" and words[1].isdigit():
                relay.value(0)
                time.sleep_ms(int(words[1]))
                relay.value(1)
                print("OK")
            elif words == ["STATE"]:
                print("OK ON" if relay.value() else "OK OFF")
            elif words == ["EXIT"]:
                print("OK")
                break
            elif words:
                print("ERR")
    finally:
        relay.value(0)
        micropython.kbd_intr(3)


main()
