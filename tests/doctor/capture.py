#!/usr/bin/env python3
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
"""Turn a real build directory into a small fixture for the doctor tests.

Usage: tests/doctor/capture.py NAME BUILD_DIR [IMAGE]
Writes tests/doctor/fixtures/NAME.tar.gz with only what scripts/ota_doctor.py reads:
  - .config and zephyr.dts of every image, unchanged
  - zephyr.map cut down to the lines the doctor looks at
  - MCUboot's zephyr.bin as zeros of the same length (only its size is used)
  - the signed image with its payload zeroed (header, sizes and TLVs are kept)
Home directories in any of these are replaced with /home/USER.
"""
import io
import re
import struct
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEEP = re.compile(r"ota_kit_set_health_check|^Discarded input sections|^Memory Configuration|"
                  r"^Linker script and memory map|^FLASH\s|^Name\s+Origin")


HOME = re.compile(rb"/home/[A-Za-z0-9_.-]+")


def add(tar, name, data):
    data = HOME.sub(b"/home/USER", data)  # no user names or home directories in the repository
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def slim_image(data):
    """Zero the code between the header and the TLVs. The doctor does not check the signature."""
    _magic, _load, hdr, prot, size, _flags = struct.unpack_from("<IIHHII", data, 0)
    end = hdr + size + prot
    return data[:hdr] + bytes(size) + data[hdr + size:] if end <= len(data) else data


def main():
    name, build = sys.argv[1], Path(sys.argv[2])
    image = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    out = HERE / "fixtures" / f"{name}.tar.gz"
    out.parent.mkdir(exist_ok=True)
    domains = (build / "domains.yaml").read_text()
    default = re.search(r"^default:\s*(\S+)", domains, flags=re.M).group(1)
    with tarfile.open(out, "w:gz") as tar:
        add(tar, "domains.yaml", domains.encode())
        for img in re.findall(r"- name:\s*(\S+)", domains):
            z = build / img / "zephyr"
            add(tar, f"{img}/zephyr/.config", (z / ".config").read_bytes())
            add(tar, f"{img}/zephyr/zephyr.dts", (z / "zephyr.dts").read_bytes())
            lines = (z / "zephyr.map").read_text(errors="replace").splitlines()
            keep = [x for i, x in enumerate(lines)
                    if KEEP.search(x) or (i and "ota_kit_set_health_check" in lines[i - 1])]
            add(tar, f"{img}/zephyr/zephyr.map", ("\n".join(keep) + "\n").encode())
            if img == "mcuboot":
                add(tar, f"{img}/zephyr/zephyr.bin", bytes((z / "zephyr.bin").stat().st_size))
        names = [image] if image else [build / default / "zephyr/zephyr.signed.bin",
                                       build / default / "zephyr/zephyr.signed.encrypted.bin"]
        for signed in names:
            if signed.exists():
                keep = signed.name if not image else "zephyr.signed.bin"
                add(tar, f"{default}/zephyr/{keep}", slim_image(signed.read_bytes()))
    print(f"{out.relative_to(HERE.parent.parent)}: {out.stat().st_size} B")


if __name__ == "__main__":
    main()
