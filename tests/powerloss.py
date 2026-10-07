#!/usr/bin/env python3
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
"""Power loss tests: cut the board's supply at chosen moments of an update.

Usage: tests/build_images.sh && tests/powerloss.py [phase ...]     phases: upload swap revert confirm erase
       tests/powerloss.py swap:4463 ...      repeat single cuts, added to the existing CSV
Needs the relay setup of docs/POWERLOSS.md, UART transport in tests/config.toml,
and: source ~/zephyrproject/.venv/bin/activate
Output: docs/data/powerloss_runs.csv and tests/logs_powerloss/<n>-<phase>.log
The design and the pass criteria are in docs/POWERLOSS.md. Do not change them to fit a result.
"""
import asyncio
import csv
import hashlib
import random
import sys
import tempfile
import time
from pathlib import Path

import serial
from intelhex import IntelHex
from smp import packet as smppacket

import ota_update_path  # noqa: F401  (adds scripts/ to sys.path)
from ota_update import session
from powerctl import PowerCtl
from run_tests import (APP_BANNER, BASE, BASE_VER, IMG, PORT, ROOT, TARGET, _smp_reset,
                       _upload_only, baseline, log, openocd, slots, upload_and_reset)
from smpclient.requests.image_management import ImageErase

SEED = 20261006
OFF_S = 2.0
BOOT_TIMEOUT_S = 120
SLOT0 = 0x08010000  # slot0_partition on disco_l475_iot1
# What is in flash for each version. The baseline is flashed from the .hex file. The build signs
# .hex and .bin separately, and an ECDSA signature differs every time, so the .bin of v1.0.0 is
# not what is on the board. The other versions arrive by upload of their .bin file.
FILES = {BASE_VER: BASE / "app/zephyr/zephyr.signed.hex",
         "2.0.0": IMG / "v2.0.0-good.bin", "2.0.1": IMG / "v2.0.1-nohealth.bin"}
MCUBOOT_FIRST = ("Using Zephyr OS build", "Starting bootloader")
FIELDS = ["n", "phase", "kind", "seed", "offset_ms", "sent_ms", "stage_before_cut", "version_after",
          "outcome", "booted_without_help", "time_to_app_s", "slots_after", "slot0_matches_file",
          "second_boot_ok", "pass", "proof", "note"]


class Console:
    """The board's UART, read line by line with the arrival time of each line."""

    def __init__(self):
        self.s = serial.Serial(PORT, 115200, timeout=0.02)
        self.buf, self.lines = b"", []

    def poll(self):
        data = self.s.read(4096)
        if data:
            now = time.monotonic()
            self.buf += data
            *done, self.buf = self.buf.split(b"\n")
            for raw in done:
                line = raw.decode(errors="replace").strip()
                self.lines.append((now, line))
                log(f"  board: {line}")

    def wait(self, patterns, timeout_s, start=0):
        """Wait for a line containing one of `patterns`. Returns (time, line) or (None, None)."""
        deadline, seen = time.monotonic() + timeout_s, start
        while time.monotonic() < deadline:
            self.poll()
            for t, line in self.lines[seen:]:
                if any(p in line for p in patterns):
                    return t, line
            seen = len(self.lines)
        return None, None

    def until(self, t_end):
        while time.monotonic() < t_end:
            self.poll()

    def close(self):
        self.s.close()


def stage(lines):
    """Last MCUboot or application milestone on the console before the cut."""
    marks = ["Starting bootloader", "Swap type", "Starting swap", "Jumping to the first image slot",
             APP_BANNER, "image confirmed", "health check FAILED"]
    seen = [m for _, line in lines for m in marks if m in line]
    return seen[-1] if seen else "nothing yet"


def slot0_matches(version):
    """Read slot 0 back over SWD and compare it with the signed image file of `version`."""
    path = FILES[version]
    want = IntelHex(str(path)).tobinstr() if path.suffix == ".hex" else path.read_bytes()
    with tempfile.NamedTemporaryFile(suffix=".bin") as f:
        openocd("init", "reset halt", f"dump_image {f.name} 0x{SLOT0:x} {len(want)}", "shutdown")
        got = Path(f.name).read_bytes()
    return hashlib.sha256(got).digest() == hashlib.sha256(want).digest()


def cut_and_observe(p, con, t0, offset_ms):
    """Cut at t0 + offset, restore after OFF_S, watch the boot, then run the checks."""
    con.until(t0 + offset_ms / 1000)
    p.off()
    t_off = p.log[-1][1]
    before = stage(con.lines)
    n_before = len(con.lines)
    con.until(t_off + OFF_S)
    # Lines can still arrive after OFF was sent, while the rail falls. They belong to the time
    # before the cut. Only lines after ON count as the boot after power came back.
    lost = [x for _, x in con.lines[n_before:]]
    before = stage(con.lines)
    n_on = len(con.lines)
    p.on()
    t_on = p.log[-1][1]
    t_app, banner = con.wait((APP_BANNER,), BOOT_TIMEOUT_S, start=n_on)
    r = {"sent_ms": round((t_off - t0) * 1000, 1), "stage_before_cut": before,
         "booted_without_help": t_app is not None,
         "note": f"{len(lost)} console lines arrived after OFF was sent" if lost else ""}
    if t_app is None:
        r.update(version_after="none", time_to_app_s="", proof=[x for _, x in con.lines[n_on:]][-6:])
        return r
    r["time_to_app_s"] = round(t_app - t_on, 2)
    if "TEST boot" in banner:  # give a test image its health window
        con.wait(("image confirmed", "health check FAILED"), 20, start=n_on)
    after = [x for _, x in con.lines[n_on:]]
    r["version_after"] = banner.split(APP_BANNER)[1].split(",")[0]
    r["proof"] = [x for x in after if any(k in x for k in ("Swap type", "E: ", "W: ", "Starting swap",
                  "downgrade", "Image version", APP_BANNER, "image confirmed", "health check"))]
    return r


def checks(r, old_ok=True):
    """Pass criteria 3 to 5 of docs/POWERLOSS.md, on a board that booted."""
    version = r["version_after"]
    state = slots()
    if version == "2.0.1" and "confirmed" not in state.split(",")[0]:
        # the image that never confirms is still in its test boot: one reset must revert it
        asyncio.run(_smp_reset())
        con = Console()
        _, banner = con.wait((APP_BANNER,), BOOT_TIMEOUT_S)
        con.close()
        version = banner.split(APP_BANNER)[1].split(",")[0] if banner else "none"
        r["note"] = (r["note"] + "; " if r["note"] else "") + f"was v2.0.1 unconfirmed, reset once, now v{version}"
        r["version_after"] = version
        state = slots()
    r["slots_after"] = state
    settled = state.startswith(f"slot0 v{version} active confirmed")
    known = version in FILES
    r["slot0_matches_file"] = slot0_matches(version) if known else False
    con = Console()                      # the dump left the MCU halted: start it again, second boot
    openocd("init", "reset run", "shutdown")
    _, banner = con.wait((APP_BANNER,), BOOT_TIMEOUT_S)
    con.close()
    r["second_boot_ok"] = bool(banner) and f"{APP_BANNER}{version}" in banner and slots() == state
    r["outcome"] = "old" if version == BASE_VER else "new" if version == "2.0.0" else version
    r["pass"] = bool(r["booted_without_help"] and known and version != "2.0.1" and settled
                     and r["slot0_matches_file"] and r["second_boot_ok"])
    return r


# ---------- the five phases. Each returns the result dict of one cut.

def phase_upload(p, pct):
    image = (IMG / "v2.0.0-good.bin").read_bytes()

    async def run():
        async with session(TARGET) as client:
            async for offset in client.upload(image, first_timeout_s=120.0, subsequent_timeout_s=20.0):
                if offset * 100 >= pct * len(image):
                    p.off()
                    return offset
    sent = asyncio.run(run())
    log(f"  host: power cut at {sent}/{len(image)} B")
    con = Console()
    r = cut_and_observe_after_off(p, con, f"upload at {sent}/{len(image)} B")
    con.close()
    return r


def cut_and_observe_after_off(p, con, before):
    """Like cut_and_observe, for phases where OFF was already sent."""
    t_off = p.log[-1][1]
    con.until(t_off + OFF_S)
    n_before = len(con.lines)
    p.on()
    t_on = p.log[-1][1]
    t_app, banner = con.wait((APP_BANNER,), BOOT_TIMEOUT_S, start=n_before)
    r = {"sent_ms": "", "stage_before_cut": before, "booted_without_help": t_app is not None, "note": ""}
    if t_app is None:
        r.update(version_after="none", time_to_app_s="", proof=[x for _, x in con.lines[n_before:]][-6:])
        return r
    r["time_to_app_s"] = round(t_app - t_on, 2)
    r["version_after"] = banner.split(APP_BANNER)[1].split(",")[0]
    r["proof"] = [x for _, x in con.lines[n_before:] if any(k in x for k in (
        "Swap type", "E: ", "W: ", "Image version", APP_BANNER))]
    return r


def phase_swap(p, offset_ms, image="v2.0.0-good.bin"):
    asyncio.run(upload_and_reset(TARGET, (IMG / image).read_bytes()))
    con = Console()
    t0, _ = con.wait(MCUBOOT_FIRST, 10)
    if t0 is None:
        con.close()
        raise RuntimeError("no MCUboot line after the reset")
    r = cut_and_observe(p, con, t0, offset_ms)
    con.close()
    return r


def phase_revert(p, offset_ms):
    asyncio.run(upload_and_reset(TARGET, (IMG / "v2.0.1-nohealth.bin").read_bytes()))
    con = Console()
    t, _ = con.wait(("health check FAILED",), 60)
    con.close()
    if t is None:
        raise RuntimeError("the nohealth image did not reach its health check")
    asyncio.run(_smp_reset())           # the reset that makes MCUboot revert
    con = Console()
    t0, _ = con.wait(MCUBOOT_FIRST, 10)
    if t0 is None:
        con.close()
        raise RuntimeError("no MCUboot line after the reset")
    r = cut_and_observe(p, con, t0, offset_ms)
    con.close()
    return r


def phase_confirm(p, offset_ms):
    asyncio.run(upload_and_reset(TARGET, (IMG / "v2.0.0-good.bin").read_bytes()))
    con = Console()
    t0, _ = con.wait((f"{APP_BANNER}2.0.0",), 60)
    if t0 is None:
        con.close()
        raise RuntimeError("v2.0.0 did not start")
    r = cut_and_observe(p, con, t0, offset_ms)
    con.close()
    return r


def phase_erase(p, offset_ms):
    asyncio.run(_upload_only("v2.0.0-good.bin"))  # make slot 1 non empty, so the erase is real
    con = Console()
    for pkt in smppacket.encode(ImageErase().BYTES):  # fire the erase, do not wait for it
        con.s.write(pkt)
    con.s.flush()
    r = cut_and_observe(p, con, time.monotonic(), offset_ms)
    r["stage_before_cut"] = "slot 1 erase running"
    con.close()
    return r


def plan():
    rng = random.Random(SEED)
    sweep = [round(100 + i * (4300 - 100) / 19) for i in range(20)]
    rand = sorted(rng.randrange(0, 4500) for _ in range(12))
    return {
        "upload": [("fixed", pct, phase_upload) for pct in (25, 50, 75, 25, 50, 75)],
        "swap": [("sweep", o, phase_swap) for o in sweep] + [("random", o, phase_swap) for o in rand],
        "revert": [("fixed", o, phase_revert) for o in (300, 1000, 1800, 2600, 3400, 4200)],
        "confirm": [("fixed", o, phase_confirm) for o in (4900, 4960, 5000, 5040, 5100, 5300)],
        "erase": [("fixed", o, phase_erase) for o in (500, 2000, 5000, 9000, 13000)],
    }


def main():
    args = sys.argv[1:] or ["upload", "swap", "revert", "confirm", "erase"]
    logs = ROOT / "tests/logs_powerloss"
    logs.mkdir(exist_ok=True)
    out = ROOT / "docs/data/powerloss_runs.csv"
    rows, n = [], 0
    # "phase:offset" repeats one cut and adds it to the existing CSV, as kind "rerun"
    extra = [a.split(":") for a in args if ":" in a]
    if extra:
        rows = list(csv.DictReader(open(out)))
        n = len(rows)
    todo = {a: plan()[a] for a in args if ":" not in a}
    fns = {"upload": phase_upload, "swap": phase_swap, "revert": phase_revert,
           "confirm": phase_confirm, "erase": phase_erase}
    for i, (phase, offset) in enumerate(extra):
        todo[f"{phase}#{i}"] = [("rerun", int(offset), fns[phase])]
    with PowerCtl() as p:   # leaving this block opens the relay, whatever happens
        for key, cuts in todo.items():
            phase = key.split("#")[0]
            for kind, offset, fn in cuts:
                n += 1
                log(f"##### cut {n}: {phase}, {kind}, offset {offset}")
                p.on()
                time.sleep(1.5)          # let the rail come up before OpenOCD talks to the target
                row = {"n": n, "phase": phase, "kind": kind, "seed": SEED, "offset_ms": offset}
                try:
                    baseline()
                    r = fn(p, offset)
                    if r["booted_without_help"]:
                        r = checks(r)
                    else:
                        r.update(outcome="no boot", slots_after="", slot0_matches_file="",
                                 second_boot_ok="", **{"pass": False})
                except Exception as e:   # a broken test run is not a result about the board
                    r = {"outcome": "TEST ERROR", "pass": "", "proof": [],
                         "note": f"{type(e).__name__}: {' '.join(str(e).split())[:160]}"}
                    p.on()
                proof = r.pop("proof", [])
                row.update(r, proof=" | ".join(proof))
                rows.append(row)
                (logs / f"{n:02d}-{phase}.log").write_text(
                    f"# cut {n}: {phase}, {kind}, offset {offset}, result {row.get('pass')}\n"
                    + "\n".join(proof) + "\n")
                log(f"##### cut {n} result: pass={row.get('pass')} outcome={row.get('outcome')} "
                    f"version={row.get('version_after')} sent={row.get('sent_ms')} ms "
                    f"stage='{row.get('stage_before_cut')}' time_to_app={row.get('time_to_app_s')} "
                    f"note={row.get('note')}")
                with open(out, "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=FIELDS)
                    w.writeheader()
                    w.writerows(rows)
        p.on()
        time.sleep(1.5)
        baseline()               # leave a known image on the board, then the relay opens
    done = [r for r in rows if r.get("pass") != ""]
    passed = sum(str(r["pass"]) == "True" for r in done)   # rows read back from the CSV are text
    log(f"{passed} of {len(done)} cuts passed, {len(rows) - len(done)} test errors")
    return 0 if done and passed == len(done) else 1


if __name__ == "__main__":
    sys.exit(main())
