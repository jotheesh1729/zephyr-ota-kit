#!/usr/bin/env python3
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
"""Failure tests. Runs every case on the real board from a known baseline.

Usage: tests/build_images.sh && tests/run_tests.py [--repeat N] [case ...]
The SMP transport (uart, ble or wifi) is set in tests/config.toml. For wifi, ESP32 only, give
the board's address in the environment variable OTA_IP.
Needs: source ~/zephyrproject/.venv/bin/activate
Output: tests/last_run.md and tests/logs/ for uart, tests/last_run_ble.md and tests/logs_ble/ for ble
"""
import asyncio
import os
import re
import signal
import socket
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import serial
from smp import packet as smppacket

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from ota_update import (  # noqa: E402
    fmt, log, read_slots, session, smp, upload_and_reset, watch_boot)
from smpclient.requests.image_management import ImageErase  # noqa: E402
from smpclient.requests.os_management import ResetWrite  # noqa: E402

CFG = tomllib.loads((ROOT / "tests/config.toml").read_text())
BLE = CFG["transport"] == "ble"
ESP = os.environ.get("BOARD", "").startswith("esp32")  # same BOARD variable as scripts/build.sh
WIFI = CFG["transport"] == "wifi"                      # SMP over UDP, ESP32 only
PORT = CFG["console_esp32" if ESP else "console"]      # UART console, for the boot log
# where SMP goes. Wi-Fi: the address the board prints when it joins, given in OTA_IP.
TARGET = (f"udp:{os.environ.get('OTA_IP', '')}" if WIFI else
          f"ble:{CFG['ble_name']}" if BLE else PORT)
# keeps BLE and ESP32 results apart from the STM32 UART ones
SUFFIX = ("_ble" if BLE else "_wifi" if WIFI else "") + ("_esp32" if ESP else "")
IMG = ROOT / f"build/test_images{SUFFIX}"
BASE = ROOT / f"build/{'esp32-' if ESP else ''}{'ble-' if BLE else 'wifi-' if WIFI else ''}v1.0.0"
BASE_VER = "1.0.0"
OPENOCD = ["openocd", "-f", "board/stm32l4discovery.cfg"]  # same config west flash uses
APP_BANNER = "OTA app v"
# Case 10, delay from the erase request to the reset. STM32: the QSPI slot erase takes about 15 s.
# ESP32: the whole erase request returns in 0.7 s, so the reset has to come much sooner.
ERASE_RESET_S = 0.1 if ESP else 3
# MCUboot and app lines worth quoting as proof
PROOF = re.compile(r"Jumping to|Starting bootloader|slot erase|rst:|abort\(\)|downgrade|Swap type|not valid|Image version|health check|simulated hang|last reset by|^E: |^W: |OTA app v")


def openocd(*cmds):
    args = OPENOCD + [x for c in cmds for x in ("-c", c)]
    subprocess.run(args, check=True, capture_output=True, timeout=120)


def hw_reset():
    if ESP:
        # EN pin through the USB serial adapter: RTS asserted with DTR released pulls EN low.
        with serial.Serial(PORT, 115200) as s:
            s.dtr = False
            s.rts = True
            time.sleep(0.2)
            s.rts = False
        return
    openocd("init", "reset run", "shutdown")


def esp_flash():
    """Erase the flash, write MCUboot and the app. Offsets are the board's partitions.

    Wi-Fi: everything below the storage partition (0x3b0000) is erased instead of the whole
    chip, because the stored network has to survive.
    """
    tool = ["esptool", "--chip", "esp32", "--port", PORT, "--baud", "921600"]
    steps = [tool + ["erase-region", "0x1000", "0x3af000"]] if WIFI else []
    steps.append(tool + ["write-flash"] + ([] if WIFI else ["-e"]) +
                 ["0x1000", f"{BASE}/mcuboot/zephyr/zephyr.bin",
                  "0x20000", f"{BASE}/app/zephyr/zephyr.signed.bin"])
    for cmd in steps:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode != 0:  # say why, a bare exit code was all that was left of one failure
            log(f"  host: esptool failed: {(r.stdout + r.stderr)[-600:]}")
            r.check_returncode()


async def _erase_slot1():
    async with session(TARGET) as c:
        await smp(c, ImageErase(), timeout_s=120.0)


async def _smp_reset():
    async with session(TARGET) as c:
        await smp(c, ResetWrite())


def slots():
    return fmt(asyncio.run(read_slots(TARGET)))


def bluetoothctl(commands, seconds):
    """Feed bluetoothctl a list of (command, pause after it). Returns its output."""
    script = "".join(f"echo '{c}'; sleep {p}; " for c, p in commands)
    r = subprocess.run(["sh", "-c", f"( {script} ) | timeout {seconds} bluetoothctl"],
                       capture_output=True, text=True)
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", r.stdout)


def ble_scan(seconds=10):
    """Scan, then return {address: name} of every device bluetoothctl knows."""
    agent = [("agent NoInputNoOutput", 1), ("default-agent", 0)]
    out = bluetoothctl(agent + [("scan on", seconds), ("devices", 1)], seconds + 10)
    return {x.split()[1]: " ".join(x.split()[2:])
            for x in out.splitlines() if x.startswith("Device ")}


def ble_find():
    """Address of the board. Discovery is not reliable on the first scan, so try 3 times."""
    for attempt in range(1, 4):
        addr = next((a for a, n in ble_scan().items() if n == CFG["ble_name"]), None)
        if addr:
            return addr
        log(f"  host: board not found in BLE scan {attempt}, scanning again")
    raise AssertionError("board not found in 3 BLE scans")


def ble_pair():
    """A mass erase wipes the board's bond but not the laptop's. Forget the board, pair again.

    The board is forgotten by address. The address is fixed, the name is not: after a
    rename the laptop can hold a bond for this address under the old name.
    """
    addr = ble_find()
    bluetoothctl([(f"remove {addr}", 2)], 6)
    assert ble_find() == addr, "board address changed between two scans"
    agent = [("agent NoInputNoOutput", 1), ("default-agent", 0)]
    out = bluetoothctl(agent + [("scan on", 4), (f"pair {addr}", 15), (f"disconnect {addr}", 2)], 30)
    assert "Pairing successful" in out, f"pairing with {addr} failed"
    log(f"--- paired with {addr}")


def baseline():
    """Known good start: internal flash wiped, MCUboot + v1.0.0 flashed, slot 1 erased."""
    log("--- baseline: mass erase, flash MCUboot + v1.0.0, erase slot 1")
    flash = lambda: openocd(  # noqa: E731
        "init", "reset halt", "stm32l4x mass_erase 0",
        f"program {BASE}/mcuboot/zephyr/zephyr.hex verify",
        f"program {BASE}/app/zephyr/zephyr.signed.hex verify",
        "reset run", "shutdown")
    if ESP:
        esp_flash()  # esptool needs the port to itself, so reset again once the reader is open
        flash = hw_reset
    lines, _ = watch_boot(PORT, stop=("WIFI: joined" if WIFI else APP_BANNER,), timeout_s=60,
                          trigger=flash)
    if WIFI:  # the board has to be at the address the test was given
        joined = next((x for x in lines if "WIFI: joined" in x), "no join line")
        assert f"IP {TARGET[4:]}," in joined, f"board not at {TARGET[4:]}: {joined}"
    if BLE:
        time.sleep(3)  # let the board start advertising
        ble_pair()
    asyncio.run(_erase_slot1())
    state = slots()
    assert state == f"slot0 v{BASE_VER} active confirmed", f"baseline is wrong: {state}"
    log(f"--- baseline ok: {state}")


def stage(image):
    """Upload, mark for test, reset. Returns (boot lines until app banner, upload error or None)."""
    try:
        asyncio.run(upload_and_reset(TARGET, (IMG / image).read_bytes()))
        err, trigger = None, None
    except Exception as e:  # upload or test request refused by the running app
        # keep the tail of the message, that is where the SMP error code is
        err, trigger = f"{type(e).__name__}: ...{' '.join(str(e).split())[-140:]}", hw_reset
        log(f"  host: upload flow failed: {err}")
    return err, trigger


def banner(lines):
    return next((x for x in reversed(lines) if APP_BANNER in x), "no app banner")


# Each case returns (actual, passed, lines). `passed` checks the security outcome only.
# It is a bool, or a string when the outcome is safe but the route differs from the expectation.

def case_good():
    err, trig = stage("v2.0.0-good.bin")
    lines, _ = watch_boot(PORT, timeout_s=60, trigger=trig)
    state = slots()
    ok = (err is None and any("Swap type: test" in x for x in lines)
          and any("image confirmed" in x for x in lines)
          and state.startswith("slot0 v2.0.0 active confirmed"))
    return f"{banner(lines)}; then confirmed. Slots: {state}", ok, lines


def case_nohealth():
    err, trig = stage("v2.0.1-nohealth.bin")
    lines, _ = watch_boot(PORT, stop=("health check FAILED",), timeout_s=60, trigger=trig)
    ran_new = any("OTA app v2.0.1" in x for x in lines)
    mid = slots()
    log(f"  host: unconfirmed state: {mid}; sending reset")
    lines2, _ = watch_boot(PORT, stop=(APP_BANNER,), timeout_s=60,
                           trigger=lambda: asyncio.run(_smp_reset()))
    state = slots()
    ok = (err is None and ran_new and "confirmed" not in mid.split(",")[0]
          and any("Swap type: revert" in x for x in lines2)
          and state.startswith(f"slot0 v{BASE_VER} active confirmed"))
    return (f"Ran v2.0.1 unconfirmed ({mid}). After reset: {banner(lines2)}. Slots: {state}",
            ok, lines + ["--- reset ---"] + lines2)


def reject_case(image):
    def run():
        err, trig = stage(image)
        lines, _ = watch_boot(PORT, stop=(APP_BANNER,), timeout_s=60, trigger=trig)
        state = slots()
        ok = (f"{APP_BANNER}{BASE_VER}" in banner(lines)
              and state.startswith(f"slot0 v{BASE_VER} active confirmed"))
        where = f"Upload refused by the app: {err}" if err else "Upload and test accepted"
        if ok and err:  # safe outcome, but not by the expected route
            ok = "PASS, different path"
        return f"{where}. After reset: {banner(lines)}. Slots: {state}", ok, lines
    return run


def case_interrupted():
    image = IMG / "v2.0.0-good.bin"
    cmd = [sys.executable, "-u", str(ROOT / "scripts/ota_update.py"), str(image), "--port", PORT]
    p = subprocess.Popen(cmd + (["--ble", CFG["ble_name"]] if BLE else
                                ["--udp", TARGET[4:]] if WIFI else []),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    seen, killed_at = b"", None
    while p.poll() is None:
        seen += os.read(p.stdout.fileno(), 4096)
        m = re.findall(rb"uploaded (\d+)/(\d+)", seen)
        if m and int(m[-1][0]) * 2 >= int(m[-1][1]):
            p.send_signal(signal.SIGKILL)
            killed_at = f"{int(m[-1][0])}/{int(m[-1][1])} B"
            break
    p.wait()
    log(f"  host: killed ota_update.py at {killed_at}")
    time.sleep(1)
    lines, _ = watch_boot(PORT, stop=(APP_BANNER,), timeout_s=60, trigger=hw_reset)
    state = slots()
    ok = (killed_at is not None and f"{APP_BANNER}{BASE_VER}" in banner(lines)
          and state.startswith(f"slot0 v{BASE_VER} active confirmed"))
    return (f"Killed at {killed_at}, board reset. {banner(lines)}. Slots: {state}", ok, lines)


def case_hang():
    """No reset is sent after the upload flow. Recovery has to come from the watchdog."""
    err, trig = stage("v2.0.5-hang.bin")
    lines, _ = watch_boot(PORT, stop=("simulated hang",), timeout_s=60, trigger=trig)
    t_hang = time.monotonic()
    hung = any("OTA app v2.0.5" in x for x in lines)
    lines2, _ = watch_boot(PORT, stop=("Starting bootloader",), timeout_s=60)
    wdt_s = time.monotonic() - t_hang
    lines3, _ = watch_boot(PORT, stop=("last reset by",), timeout_s=60)
    state = slots()
    ok = (err is None and hung
          and any("Swap type: revert" in x for x in lines3)
          and any("last reset by WATCHDOG" in x for x in lines3)
          and state.startswith(f"slot0 v{BASE_VER} active confirmed"))
    return (f"v2.0.5 booted and hung. Chip reset itself {wdt_s:.1f} s later, no reset sent. "
            f"{banner(lines3)}. Slots: {state}", ok,
            lines + ["--- no reset sent, waiting ---"] + lines2 + lines3)


def case_early_hang():
    """The new image hangs before main() and before the kit arms its watchdog.

    Only a watchdog that MCUboot started can end that. No reset is sent by the script.
    """
    err, trig = stage("v2.0.6-earlyhang.bin")
    lines, _ = watch_boot(PORT, stop=("Jumping to the first image slot",), timeout_s=90, trigger=trig)
    t_jump = time.monotonic()
    swapped = any("Image version: v2.0.6" in x for x in lines)
    lines2, _ = watch_boot(PORT, stop=("Starting bootloader",), timeout_s=120)
    reset_s = time.monotonic() - t_jump
    self_reset = any("Starting bootloader" in x for x in lines2)
    ran = any(APP_BANNER in x for x in lines2)  # the hung image must not get as far as its banner
    lines3 = []
    if self_reset:
        lines3, _ = watch_boot(PORT, stop=("last reset by",), timeout_s=90)
    else:
        log("  host: no reset by the board in 120 s, resetting it from the host")
        lines3, _ = watch_boot(PORT, stop=("last reset by",), timeout_s=90, trigger=hw_reset)
    state = slots()
    ok = (err is None and swapped and self_reset and not ran
          and any("Swap type: revert" in x for x in lines3)
          and state.startswith(f"slot0 v{BASE_VER} active confirmed"))
    how = (f"The board reset itself {reset_s:.1f} s after the jump" if self_reset else
           "The board stayed hung for 120 s and was reset by the test")
    return (f"v2.0.6 was swapped in and hung before main(). {how}. {banner(lines3)}. Slots: {state}",
            ok, lines + ["--- no reset sent, waiting ---"] + lines2 + lines3)


async def _upload_only(image):
    async with session(TARGET) as c:
        async for _ in c.upload((IMG / image).read_bytes(), first_timeout_s=120.0,
                                subsequent_timeout_s=20.0):
            pass


def case_reset_in_erase():
    """Hardware reset while the QSPI flash is busy erasing. The MCU reset does not reset the flash.

    UART only: it writes a raw SMP frame to the serial port so that it does not wait for the reply.
    """
    if ESP:
        return case_reset_in_erase_traced()
    asyncio.run(_upload_only("v2.0.0-good.bin"))  # make slot 1 non empty, so the erase is real
    with serial.Serial(PORT, 115200, timeout=1) as s:
        for pkt in smppacket.encode(ImageErase().BYTES):  # fire the erase, do not wait for it
            s.write(pkt)
        s.flush()
    time.sleep(ERASE_RESET_S)
    t0 = time.monotonic()
    lines, _ = watch_boot(PORT, stop=(APP_BANNER,), timeout_s=90, trigger=hw_reset)
    boot_s = time.monotonic() - t0
    aborted = any("abort()" in x for x in lines)
    state = slots()
    ok = (not aborted and boot_s < 5 and f"{APP_BANNER}{BASE_VER}" in banner(lines)
          and state.startswith(f"slot0 v{BASE_VER} active confirmed"))
    return (f"Reset {ERASE_RESET_S} s after the erase request. App banner {boot_s:.1f} s after the reset command, "
            f"MCUboot abort: {'yes' if aborted else 'no'}. {banner(lines)}. Slots: {state}",
            ok, lines)


def _raw_erase(reset_after_s=None):
    """Send an erase request without waiting for the answer and read the app's trace lines.

    The ESP32 example app prints "slot erase start" and "slot erase done" (CONFIG_APP_ERASE_TRACE).
    `reset_after_s`: reset the chip this long after the start line was read. None: no reset.
    Returns (seconds from the start line to the done line or None, seconds from the start line
    to the reset or None, console lines with host times in seconds after the start line).
    """
    done_s = reset_s = t_start = None
    lines, buf = [], b""
    with serial.Serial(PORT, 115200, timeout=0.005) as s:
        if WIFI:  # the request goes over UDP, the trace lines still come on the UART console
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
                u.sendto(ImageErase().BYTES, (TARGET[4:], 1337))
        else:
            for pkt in smppacket.encode(ImageErase().BYTES):
                s.write(pkt)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            buf += s.read(4096)
            now = time.monotonic()
            *whole, buf = buf.split(b"\n")
            for raw in whole:
                line = raw.decode(errors="replace").strip()
                if "slot erase start" in line and t_start is None:
                    t_start = now
                if t_start is not None:
                    lines.append(f"+{now - t_start:.3f} s {line}")
                    log(f"  board: {lines[-1]}")
                if "slot erase done" in line and t_start is not None and done_s is None:
                    done_s = now - t_start
            if (reset_after_s is not None and reset_s is None and t_start is not None
                    and time.monotonic() - t_start >= reset_after_s):
                s.dtr = False
                s.rts = True   # EN low: the chip is in reset from here
                reset_s = time.monotonic() - t_start
                lines.append(f"+{reset_s:.3f} s --- reset sent ---")
                time.sleep(0.2)
                s.rts = False
            if (done_s is not None and reset_after_s is None) or any(APP_BANNER in x for x in lines):
                break
    return done_s, reset_s, lines


def erase_sweep(delays_ms):
    """ESP32: reset at several points of a slot 1 erase. One CSV row per delay."""
    import csv
    rows = []
    for ms in delays_ms:
        baseline()
        asyncio.run(_upload_only("v2.0.0-good.bin"))
        done_s, reset_s, lines = _raw_erase(reset_after_s=ms / 1000)
        (ROOT / f"tests/logs{SUFFIX}/erase-sweep-{ms}ms.log").write_text("\n".join(lines) + "\n")
        done_first = done_s is not None and done_s < reset_s
        state = slots()
        rows.append((ms, f"{reset_s * 1000:.1f}", "" if done_s is None else f"{done_s * 1000:.0f}",
                     "after the erase" if done_first else "inside the erase",
                     "yes" if any("abort()" in x for x in lines) else "no", banner(lines), state))
        log(f"=== erase sweep {ms} ms: {rows[-1]}")
    with open(ROOT / f"docs/data/erase_sweep{SUFFIX}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["delay_ms", "reset_sent_ms_after_start_line", "done_line_ms", "reset_lands",
                    "mcuboot_abort", "app_banner_after_reset", "slots"])
        w.writerows(rows)
    baseline()


def case_reset_in_erase_traced():
    """ESP32: the erase is short, so the reset is tied to the app's "slot erase start" line.

    First an erase that is left alone, to measure it. Then the same erase with a reset.
    """
    asyncio.run(_upload_only("v2.0.0-good.bin"))
    full_s, _, ref = _raw_erase()
    asyncio.run(_upload_only("v2.0.0-good.bin"))
    _, reset_s, lines = _raw_erase(reset_after_s=0)
    cut = [x for x in lines if "rst:" in x]            # first line of the ROM after the reset
    done_before_reset = any("slot erase done" in x for x in lines)
    state = slots()
    proven = (full_s is not None and reset_s is not None and reset_s < full_s
              and not done_before_reset and bool(cut))
    ok = (proven and not any("abort()" in x for x in lines) and f"{APP_BANNER}{BASE_VER}" in banner(lines)
          and state.startswith(f"slot0 v{BASE_VER} active confirmed"))
    full = "no done line" if full_s is None else f"{full_s * 1000:.0f} ms"
    at = "no start line" if reset_s is None else f"{reset_s * 1000:.1f} ms"
    return (f"Erase left alone: start to done {full}. Second erase: reset {at} after the start line, "
            f"done line seen before the reset: {'yes' if done_before_reset else 'no'}. "
            f"{banner(lines)}. Slots: {state}",
            ok, ["--- erase left alone ---"] + ref + ["--- erase with reset ---"] + lines)


def downgrade_case(newer, version):
    """Update to a newer version, then offer the old v1.0.0 again."""
    def run():
        err, trig = stage(newer)
        lines, _ = watch_boot(PORT, timeout_s=60, trigger=trig)
        up = slots()
        if not up.startswith(f"slot0 v{version} active confirmed"):
            return f"Could not get to v{version} first: {up}", False, lines
        err, trig = stage("v1.0.0-old.bin")
        lines2, _ = watch_boot(PORT, stop=(APP_BANNER,), timeout_s=60, trigger=trig)
        state = slots()
        ok = (f"{APP_BANNER}{version}" in banner(lines2)
              and state.startswith(f"slot0 v{version} active confirmed"))
        where = (f"v1.0.0 refused at upload: {err}" if err else
                 "v1.0.0 accepted by the SMP server, marked for test")
        return (f"On v{version}. {where}. After reset: {banner(lines2)}. Slots: {state}",
                ok, lines + ["--- now offering v1.0.0 ---"] + lines2)
    return run


REJECT = "Upload ok, test, reset, MCUboot rejects the image, v1.0.0 still runs"
CASES = {
    "1-good": ("Swap, confirm, runs v2.0.0", case_good),
    "2-nohealth": ("Swap, runs v2.0.1 without confirm, reset, rollback to v1.0.0", case_nohealth),
    "3-badkey": (REJECT, reject_case("v2.0.2-badkey.bin")),
    "4-unsigned": (REJECT, reject_case("v2.0.3-unsigned.bin")),
    "4b-nosig": (REJECT, reject_case("v2.0.3-nosig.bin")),
    "5-corrupt": (REJECT, reject_case("v2.0.4-corrupt.bin")),
    "8-hang": ("Hung test image, IWDG resets the chip, MCUboot reverts, v1.0.0 runs, "
               "no reset from the script", case_hang),
    "9-early-hang": ("Image that hangs before main(): a watchdog from MCUboot resets the chip, "
                     "MCUboot reverts, v1.0.0 runs, no reset from the script", case_early_hang),
    "10-reset-in-erase": ("Reset during a slot 1 erase, v1.0.0 boots within 5 s, no MCUboot abort",
                          case_reset_in_erase),
    "7-downgrade": ("v1.0.0 over v2.0.0 is rejected, v2.0.0 keeps running",
                    downgrade_case("v2.0.0-good.bin", "2.0.0")),
    "6-interrupted": ("Kill upload near 50%, reset, v1.0.0 still runs", case_interrupted),
}


def main():
    # Usage: run_tests.py [--repeat N] [case ...]   or, ESP32: run_tests.py erase-sweep MS [MS ...]
    args, repeat = sys.argv[1:], 1
    if args[:1] == ["erase-sweep"]:  # ESP32 only: run_tests.py erase-sweep 100 300 500
        erase_sweep([int(x) for x in args[1:]])
        return 0
    if args[:1] == ["--repeat"]:
        repeat, args = int(args[1]), args[2:]
    if BLE or WIFI:
        CASES.pop("10-reset-in-erase")  # UART only, see the case
    names = (args or list(CASES)) * repeat
    logs = ROOT / f"tests/logs{SUFFIX}"
    logs.mkdir(exist_ok=True)
    log(f"board: {'esp32' if ESP else 'stm32'}, transport: {CFG['transport']}, SMP target: {TARGET}")
    rows = []
    for name in names:
        expected, fn = CASES[name]
        log(f"=== case {name}: expect: {expected}")
        baseline()
        try:
            actual, ok, lines = fn()
        except Exception as e:
            actual, ok, lines = f"TEST ERROR {type(e).__name__}: {e}", False, []
        (logs / f"{name}.log").write_text("\n".join(lines) + "\n")
        proof = "<br>".join(f"`{x}`" for x in lines if PROOF.search(x)) or "none"
        result = ok if isinstance(ok, str) else "PASS" if ok else "FAIL"
        log(f"=== case {name}: {result}: {actual}")
        rows.append((name, expected, actual, result, proof))
    baseline()

    if repeat > 1:  # raw rows for docs/RESULTS.md
        import csv
        (ROOT / "docs/data").mkdir(exist_ok=True)
        with open(ROOT / f"docs/data/failure_runs{SUFFIX}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["n", "case", "result", "actual"])
            w.writerows((n + 1, r[0], r[3], r[2]) for n, r in enumerate(rows))

    out = ["| Case | Expected | Actual | Result | Boot log proof |", "|---|---|---|---|---|"]
    out += ["| " + " | ".join(c.replace("|", "/") for c in r) + " |" for r in rows]
    (ROOT / f"tests/last_run{SUFFIX}.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0 if all(r[3].startswith("PASS") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
