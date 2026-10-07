#!/usr/bin/env python3
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
"""Measurement. Runs the good update N times, and on UART one near full slot update.

Usage: tests/build_images.sh && tests/measure.py [N]
The SMP transport (uart or ble) is set in tests/config.toml.
Needs: source ~/zephyrproject/.venv/bin/activate
Output: docs/data/update_runs.csv and big_image_run.csv, or update_runs_ble.csv for ble
"""
import csv
import subprocess
import sys

import ota_update_path  # noqa: F401  (adds scripts/ to sys.path)
import ota_update
from ota_doctor import Image
from run_tests import BASE, BLE, IMG, PORT, ROOT, SUFFIX, TARGET, baseline, log

FIELDS = ["run", "target", "ok", "version", "image_bytes", "upload_s", "swap_s", "total_s", "error"]


def one(n, target, image):
    try:
        r = ota_update.run(TARGET, str(image), console=PORT)
        r["error"] = ""
    except Exception as e:  # keep going, a failed run is a data point
        r = {"ok": False, "error": f"{type(e).__name__}: {' '.join(str(e).split())[-120:]}"}
        log(f"run {n} FAILED: {r['error']}")
        baseline()
    return {"run": n, "target": target, **r}


def resign(binary_version, new_version):
    """Sign build/<prefix>v<binary_version>'s zephyr.bin again under a new version number.

    Same imgtool arguments as the Zephyr build uses: header size, slot 0 size, write alignment.
    """
    app = Image(BASE.parent / BASE.name.replace("1.0.0", binary_version) / "app")
    out = ROOT / f"build/measure_images{SUFFIX}/v{new_version}.bin"
    out.parent.mkdir(exist_ok=True)
    subprocess.run(["imgtool", "sign", "--version", new_version,
                    "--header-size", app.val("ROM_START_OFFSET"),
                    "--slot-size", hex(app.partition("slot0_partition")[1]), "--align", "8",
                    "-k", app.val("MCUBOOT_SIGNATURE_KEY_FILE"),
                    str(app.dir / "zephyr/zephyr.bin"), str(out)], check=True, capture_output=True)
    return out


def write(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main():
    n_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    data = ROOT / "docs/data"
    data.mkdir(exist_ok=True)

    # Alternate between the v1.1.0 and v1.0.0 binaries, so slot 1 always holds the previous
    # image, as in the field. Downgrade prevention needs every update to have a higher version,
    # so each run gets the same binary signed again with the next version number.
    baseline()  # board starts on v1.0.0
    rows = []
    for n in range(1, n_runs + 1):
        target = f"1.{10 + n}.0"
        log(f"##### run {n}/{n_runs}: update to v{target}")
        rows.append(one(n, target, resign("1.1.0" if n % 2 else "1.0.0", target)))
        write(data / f"update_runs{SUFFIX}.csv", rows)

    if SUFFIX:  # the 840 K image was only measured on the STM32 over UART
        baseline()
        return

    # One image that nearly fills slot 1. Swap and upload scale with image size.
    ota_update.BOOT_TIMEOUT_S = 600
    baseline()
    log("##### big image run")
    write(data / "big_image_run.csv", [one(1, "1.3.0", IMG / "v1.3.0-big.bin")])
    baseline()


if __name__ == "__main__":
    main()
