#!/usr/bin/env python3
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
"""OTA doctor: read a finished Zephyr build and warn about OTA configuration mistakes.

Usage: scripts/ota_doctor.py BUILD_DIR [--image FILE] [--json OUT.json] [--release]
                             [--slot0-erase-size N] [--slot1-erase-size N]

BUILD_DIR is a sysbuild build directory (with domains.yaml), or a single image build.
It reads zephyr/.config, zephyr/zephyr.dts and zephyr/zephyr.map of the application and of
MCUboot, and the signed image if there is one. Nothing is flashed, no board is needed.

Exit code: 1 if any rule reports FAIL, else 0.
Standard library only. Rules, their evidence and the limits of the tool: docs/DOCTOR.md.
A report without FAIL does not prove the board is safe.
"""
import argparse
import json
import re
import struct
import sys
from pathlib import Path

PASS, INFO, WARN, FAIL, UNKNOWN = "PASS", "INFO", "WARN", "FAIL", "UNKNOWN"

# Largest watchdog timeout per SoC series, in ms. Only entries with a source. No entry = unknown.
# Key: (CONFIG_SOC_SERIES value, compatible of the watchdog0 node).
WDT_MAX_MS = {
    ("stm32l4x", "st,stm32-watchdog"): (
        32768,
        "prescaler 256 x (reload 0xFFF + 1) / LSI 32000 Hz. Constants in Zephyr "
        "drivers/watchdog/wdt_iwdg_stm32.c and the STM32L4 HAL (LSI_VALUE, IWDG_RLR_RL, "
        "no /1024 prescaler). Seen on the board: 300000 ms refused with -22, 30000 ms accepted."),
}

# MCUboot's bundled development keys. Their private halves are public (MCUboot readme-zephyr.md).
DEV_ENC_KEY_NAMES = ("enc-rsa2048-priv.pem", "enc-ec256-priv.pem", "enc-x25519-priv.pem")
DEV_KEY_NAMES = ("root-rsa-2048.pem", "root-rsa-3072.pem", "root-ec-p256.pem", "root-ec-p384.pem",
                 "root-ed25519.pem", "root-ec-p256-pkcs8.pem")

IMAGE_MAGIC = 0x96F3B83D
TLV_INFO_MAGIC, TLV_PROT_INFO_MAGIC = 0x6907, 0x6908
TLV_SIG = {0x20: "RSA2048", 0x22: "ECDSA", 0x23: "RSA3072", 0x24: "ED25519"}
BOOT_MAGIC = bytes([0x77, 0xC2, 0x95, 0xF3, 0x60, 0xD2, 0xEF, 0x7F,
                    0x35, 0x52, 0x50, 0x0F, 0x2C, 0xB6, 0x79, 0x80])


# ---------- inputs

class Node:
    def __init__(self, name, labels, parent):
        self.name, self.labels, self.parent = name, labels, parent
        self.props, self.children = {}, []

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def cells(self, prop):
        """Numbers of a <...> property, or None."""
        v = self.props.get(prop)
        m = re.fullmatch(r"<\s*(.*?)\s*>", v or "")
        try:
            return [int(x, 0) for x in m.group(1).split()] if m else None
        except ValueError:
            return None

    def compat(self):
        return re.findall(r'"([^"]+)"', self.props.get("compatible", ""))


def parse_dts(text):
    """Parse the generated zephyr.dts. Enough for nodes, labels and raw property values."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    root = cur = None
    for stmt in re.finditer(r"([^;{}]*)([;{}])", text):
        head, end = stmt.group(1).strip(), stmt.group(2)
        if end == "{":
            m = re.fullmatch(r"((?:[\w]+\s*:\s*)*)([^\s{]+)", head)
            if not m:
                continue
            node = Node(m.group(2), re.findall(r"(\w+)\s*:", m.group(1)), cur)
            if cur is None:
                root = node
            else:
                cur.children.append(node)
            cur = node
        elif end == "}":
            cur = cur.parent if cur and cur.parent else cur
        elif head and cur is not None and not head.startswith("/"):
            key, _, value = head.partition("=")
            cur.props[key.strip()] = value.strip() if value else True
    return root


class Image:
    """One Zephyr image of the build: its .config, devicetree and map file."""

    def __init__(self, build_dir):
        z = Path(build_dir) / "zephyr"
        self.dir = Path(build_dir)
        self.config = {}
        for line in (z / ".config").read_text().splitlines():
            m = re.match(r"(CONFIG_\w+)=(.*)", line)
            if m:
                self.config[m.group(1)] = m.group(2).strip('"')
        dts = z / "zephyr.dts"
        self.dt = parse_dts(dts.read_text()) if dts.exists() else None
        self.map = (z / "zephyr.map").read_text(errors="replace") if (z / "zephyr.map").exists() else ""
        self.bin = z / "zephyr.bin"

    def on(self, name):
        return self.config.get("CONFIG_" + name) == "y"

    def val(self, name, default=None):
        return self.config.get("CONFIG_" + name, default)

    def num(self, name, default=None):
        v = self.val(name)
        return int(v, 0) if v not in (None, "") else default

    def label(self, label):
        return next((n for n in self.dt.walk() if label in n.labels), None) if self.dt else None

    def ref(self, node_name, prop):
        """Label that /<node_name>/<prop> points to, e.g. ref("chosen", "zephyr,code-partition")."""
        node = next((n for n in self.dt.children if n.name == node_name), None) if self.dt else None
        m = re.fullmatch(r"&(\w+)", str(node.props.get(prop, "")) if node else "")
        return m.group(1) if m else None

    def partition(self, label):
        """(offset, size, flash node) of a partition label, or None."""
        n = self.label(label)
        reg = n.cells("reg") if n else None
        if not reg or len(reg) < 2:
            return None
        return reg[0], reg[1], n.parent.parent if n.parent else None

    def flash_region(self):
        """Length of the FLASH region the linker used, from the map file."""
        m = re.search(r"^FLASH\s+0x[0-9a-f]+\s+(0x[0-9a-f]+)", self.map, flags=re.M)
        return int(m.group(1), 16) if m else None


def parse_signed_image(path):
    """Fields of an MCUboot image file. Raises ValueError if it is not one."""
    data = Path(path).read_bytes()
    if len(data) < 32:
        raise ValueError("file too short")
    magic, _load, hdr_size, prot_tlv, img_size, flags = struct.unpack_from("<IIHHII", data, 0)
    if magic != IMAGE_MAGIC:
        raise ValueError(f"no MCUboot header magic (found 0x{magic:08x})")
    major, minor, rev, build = struct.unpack_from("<BBHI", data, 20)
    off = hdr_size + img_size + prot_tlv
    tlvs, total = [], off
    if off + 4 <= len(data):
        tmagic, tlen = struct.unpack_from("<HH", data, off)
        if tmagic == TLV_INFO_MAGIC:
            total, p = off + tlen, off + 4
            while p + 4 <= off + tlen:
                ttype, tl = struct.unpack_from("<HH", data, p)
                tlvs.append(ttype)
                p += 4 + tl
    confirmed = data[-16:] == BOOT_MAGIC and data[-24] == 0x01
    return {"file_size": len(data), "image_size": total, "version": f"{major}.{minor}.{rev}+{build}",
            "tlvs": tlvs, "padded": data[-16:] == BOOT_MAGIC, "confirmed": confirmed,
            "encrypted": bool(flags & 0x0C)}  # IMAGE_F ENCRYPTED_AES128 0x4, ENCRYPTED_AES256 0x8


class Ctx:
    def __init__(self, build_dir, image_path=None, release=False, erase_sizes=(None, None)):
        build_dir = Path(build_dir)
        self.release = release
        self.erase_sizes = erase_sizes  # from the command line, for flashes the devicetree does not describe
        domains = build_dir / "domains.yaml"
        self.app = self.boot = None
        if domains.exists():
            text = domains.read_text()
            default = re.search(r"^default:\s*(\S+)", text, flags=re.M).group(1)
            dirs = dict(re.findall(r"- name:\s*(\S+)\s*\n\s*build_dir:\s*(\S+)", text))
            # the recorded paths are absolute, the directory may have moved: use the names
            self.app = Image(build_dir / default)
            if "mcuboot" in dirs and (build_dir / "mcuboot/zephyr/.config").exists():
                self.boot = Image(build_dir / "mcuboot")
        elif (build_dir / "zephyr/.config").exists():
            self.app = Image(build_dir)
        else:
            raise SystemExit(f"{build_dir}: no domains.yaml and no zephyr/.config, not a build directory")

        self.image, self.image_error, self.image_path = None, None, None
        candidate = Path(image_path) if image_path else self.app.dir / "zephyr/zephyr.signed.bin"
        encrypted = self.app.dir / "zephyr/zephyr.signed.encrypted.bin"
        if not image_path and encrypted.exists():
            candidate = encrypted  # this is the file that gets uploaded
        if candidate.exists():
            self.image_path = candidate
            try:
                self.image = parse_signed_image(candidate)
            except ValueError as e:
                self.image_error = str(e)

    # shared facts
    def mode(self):
        b = self.boot
        if not b:
            return None
        for name, mode in (("BOOT_SWAP_USING_MOVE", "move"), ("BOOT_SWAP_USING_OFFSET", "offset"),
                           ("BOOT_SWAP_USING_SCRATCH", "scratch"), ("BOOT_UPGRADE_ONLY", "overwrite"),
                           ("BOOT_DIRECT_XIP", "direct-xip"), ("BOOT_RAM_LOAD", "ram-load"),
                           ("SINGLE_APPLICATION_SLOT", "single")):
            if b.on(name):
                return mode
        return "scratch"  # MCUboot's swap default when nothing else is selected

    def sector(self):
        """(sector size used by MCUboot, description, hw size slot0, hw size slot1). Sizes may be None."""
        img = self.boot or self.app
        hw = []
        for label, given in zip(("slot0_partition", "slot1_partition"), self.erase_sizes):
            p = img.partition(label)
            cells = p[2].cells("erase-block-size") if p and p[2] else None
            hw.append(cells[0] if cells else given)
        logical = self.boot.num("MCUBOOT_LOGICAL_SECTOR_SIZE", 0) if self.boot else 0
        if logical:
            return logical, f"logical sector 0x{logical:x}", hw[0], hw[1]
        if hw[0] and hw[0] == hw[1]:
            return hw[0], f"hardware sector {hw[0]}", hw[0], hw[1]
        return None, "unknown", hw[0], hw[1]

    def max_image(self):
        """(largest image MCUboot can swap, how it was worked out), or (None, reason)."""
        img = self.boot or self.app
        s0, s1 = img.partition("slot0_partition"), img.partition("slot1_partition")
        sector = self.sector()[0]
        footer = self.app.num("MCUBOOT_UPDATE_FOOTER_SIZE", 0)
        if not (s0 and s1 and sector):
            return None, "slot sizes or sector size unknown"
        if not footer:
            return None, "CONFIG_MCUBOOT_UPDATE_FOOTER_SIZE is 0, trailer size not known from the build"
        mode = self.mode()
        if mode == "move":      # MCUboot design.md: (N-1) * sector - trailer sectors
            limit = min((s0[1] // sector - 1) * sector, s1[1]) - footer
            return limit, (f"min(({s0[1] // sector} - 1) x {sector}, slot1 {s1[1]}) "
                           f"- trailer {footer}")
        if mode in ("offset", "scratch", "overwrite"):
            return min(s0[1], s1[1]) - footer, f"min(slot0 {s0[1]}, slot1 {s1[1]}) - trailer {footer}"
        return None, f"no size rule for mode {mode}"


# ---------- rules

RULES = []


def rule(rule_id, title):
    def wrap(fn):
        RULES.append((rule_id, title, fn))
        return fn
    return wrap


def need_boot(c):
    return None if c.boot else (UNKNOWN, "No MCUboot build found next to the application.",
                                "Build with sysbuild and pass the sysbuild build directory.")


@rule("LAYOUT-01", "Partitions for MCUboot, slot 0 and slot 1 exist")
def _(c):
    missing = [x for x in ("boot_partition", "slot0_partition", "slot1_partition")
               if not c.app.partition(x)]
    if missing:
        return FAIL, f"Missing in the application devicetree: {', '.join(missing)}.", \
            "Add the partitions, see docs/PORTING.md step 2."
    p = {x: c.app.partition(x) for x in ("boot_partition", "slot0_partition", "slot1_partition")}
    return PASS, "; ".join(f"{k} 0x{v[0]:x} + {v[1]} B on {v[2].name}" for k, v in p.items()), ""


@rule("LAYOUT-02", "Each image is linked into its own partition")
def _(c):
    out = []
    app_cp = c.app.ref("chosen", "zephyr,code-partition")
    if c.app.on("BOOTLOADER_MCUBOOT") and app_cp != "slot0_partition":
        out.append(f"application code partition is {app_cp}, expected slot0_partition")
    if c.boot:
        boot_cp = c.boot.ref("chosen", "zephyr,code-partition")
        if boot_cp != "boot_partition":
            out.append(f"MCUboot code partition is {boot_cp}, expected boot_partition")
    if not c.app.on("BOOTLOADER_MCUBOOT"):
        out.append("CONFIG_BOOTLOADER_MCUBOOT is off in the application")
    if out:
        return FAIL, "; ".join(out) + ".", \
            "An overlay in sysbuild/mcuboot.overlay replaces MCUboot's own one. Put " \
            "zephyr,code-partition = &boot_partition back. See docs/PORTING.md step 6."
    return PASS, f"application in {app_cp}" + (", MCUboot in boot_partition" if c.boot else ""), ""


@rule("LAYOUT-03", "MCUboot and the application see the same partitions")
def _(c):
    if (r := need_boot(c)):
        return r
    diff = []
    for label in ("boot_partition", "slot0_partition", "slot1_partition", "scratch_partition"):
        a, b = c.app.partition(label), c.boot.partition(label)
        if (a and a[:2]) != (b and b[:2]):
            diff.append(f"{label}: application {a and a[:2]}, MCUboot {b and b[:2]}")
    if diff:
        return FAIL, "; ".join(diff) + ".", \
            "An overlay reached only one image. Apply it to both, see docs/PORTING.md step 6."
    return PASS, "boot, slot 0, slot 1 and scratch match in both devicetrees", ""


@rule("SECTOR-01", "Both slots use one sector size")
def _(c):
    if (r := need_boot(c)):
        return r
    if c.mode() not in ("move", "offset", "scratch"):
        return INFO, f"Mode {c.mode()} does not swap sectors.", ""
    size, how, hw0, hw1 = c.sector()
    logical = c.boot.num("MCUBOOT_LOGICAL_SECTOR_SIZE", 0)
    if logical:
        bad = [f"slot {i} hardware sector {h}" for i, h in enumerate((hw0, hw1)) if h and logical % h]
        if bad:
            return FAIL, f"Logical sector 0x{logical:x} is not a multiple of: {', '.join(bad)}.", \
                "Set the logical sector size to a multiple of every hardware erase size."
        unknown = [str(i) for i, h in enumerate((hw0, hw1)) if not h]
        note = (f" Erase size of slot {' and '.join(unknown)} is not in the devicetree, "
                "check it against the flash datasheet.") if unknown else ""
        return (WARN if unknown else PASS), \
            f"MCUboot uses {how} (hardware: slot 0 {hw0}, slot 1 {hw1}).{note}", \
            ("Logical sectors are marked experimental in MCUboot." if not unknown else
             "The logical sector size must be a multiple of the real erase size of that flash.")
    if hw0 and hw1 and hw0 != hw1:
        return FAIL, f"Slot 0 erases in {hw0} B, slot 1 in {hw1} B, and no logical sector size is set.", \
            "MCUboot refuses with 'not same sector layout'. Set " \
            "SB_CONFIG_OTA_KIT_MCUBOOT_LOGICAL_SECTOR_SIZE to the larger one. PORTING.md step 2."
    if not (hw0 and hw1):
        return UNKNOWN, f"Erase size not in the devicetree (slot 0: {hw0}, slot 1: {hw1}). " \
            "Cannot tell whether the slots match.", \
            "Look up the erase size in the flash datasheet and pass it with --slot1-erase-size. " \
            "If it differs from the other slot, set a logical sector size."
    return PASS, f"both slots erase in {hw0} B", ""


@rule("SECTOR-02", "Slots start and end on sector boundaries")
def _(c):
    size = c.sector()[0]
    if not size:
        return UNKNOWN, "Sector size unknown, see SECTOR-01.", ""
    img = c.boot or c.app
    bad = []
    for label in ("slot0_partition", "slot1_partition"):
        p = img.partition(label)
        if p and (p[0] % size or p[1] % size):
            bad.append(f"{label} offset 0x{p[0]:x} size {p[1]} ({p[1] / size:.2f} sectors)")
    if bad:
        return FAIL, f"Not a whole number of {size} B sectors: {'; '.join(bad)}.", \
            "Change the partition so that offset and size are multiples of the sector size."
    return PASS, f"slot 0 and slot 1 are whole multiples of {size} B", ""


@rule("SECTOR-03", "Sector counts fit the swap algorithm")
def _(c):
    if (r := need_boot(c)):
        return r
    size, mode = c.sector()[0], c.mode()
    s0, s1 = c.boot.partition("slot0_partition"), c.boot.partition("slot1_partition")
    if not (size and s0 and s1):
        return UNKNOWN, "Sector size or slots unknown.", ""
    n0, n1 = s0[1] // size, s1[1] // size
    limit = c.boot.num("BOOT_MAX_IMG_SECTORS")
    if limit and max(n0, n1) > limit:
        return FAIL, f"{max(n0, n1)} sectors in a slot, CONFIG_BOOT_MAX_IMG_SECTORS is {limit}.", \
            "Raise SB_CONFIG_OTA_KIT_MCUBOOT_MAX_IMG_SECTORS."
    if mode == "move":
        if n0 not in (n1, n1 + 1):
            return FAIL, f"Swap using move: slot 0 has {n0} sectors, slot 1 has {n1}. " \
                "MCUboot accepts equal counts or slot 0 one larger.", \
                "MCUboot refuses with 'not a compatible amount of sectors'. Resize a slot. PORTING.md step 2."
        return PASS, f"swap using move, slot 0 {n0} sectors, slot 1 {n1}" + \
            (" (optimal: one more in slot 0)" if n0 == n1 + 1 else " (equal: one sector of slot 1 stays unused)"), ""
    if mode == "offset":
        if n1 not in (n0, n0 + 1):
            return FAIL, f"Swap using offset: slot 0 has {n0} sectors, slot 1 has {n1}. " \
                "MCUboot accepts equal counts or slot 1 one larger.", "Resize a slot."
        return PASS, f"swap using offset, slot 0 {n0} sectors, slot 1 {n1}", ""
    if mode == "scratch" and s0[1] != s1[1]:
        return WARN, f"Swap using scratch assumes equal slots: slot 0 {s0[1]} B, slot 1 {s1[1]} B.", \
            "Make the slots the same size (MCUboot design.md)."
    return PASS, f"mode {mode}, slot 0 {n0} sectors, slot 1 {n1}", ""


@rule("SWAP-01", "Scratch partition matches the swap mode")
def _(c):
    if (r := need_boot(c)):
        return r
    scratch, mode = c.boot.partition("scratch_partition"), c.mode()
    if mode == "scratch" and not scratch:
        return FAIL, "Swap using scratch is selected and there is no scratch_partition.", \
            "Add a scratch partition, or select swap using move (the ota-kit snippet does)."
    if mode != "scratch" and scratch:
        return INFO, f"scratch_partition ({scratch[1]} B) exists but mode {mode} does not use it.", ""
    return PASS, f"mode {mode}, scratch partition {'present' if scratch else 'not needed'}", ""


@rule("SWAP-02", "Application and MCUboot agree on the mode")
def _(c):
    if (r := need_boot(c)):
        return r
    pairs = {"move": "MCUBOOT_BOOTLOADER_MODE_SWAP_USING_MOVE", "offset": "MCUBOOT_BOOTLOADER_MODE_SWAP_USING_OFFSET",
             "scratch": "MCUBOOT_BOOTLOADER_MODE_SWAP_SCRATCH", "overwrite": "MCUBOOT_BOOTLOADER_MODE_OVERWRITE_ONLY"}
    want = pairs.get(c.mode())
    if want and not c.app.on(want):
        return FAIL, f"MCUboot runs mode {c.mode()}, the application was built without CONFIG_{want}.", \
            "Build both with sysbuild so the mode is set in one place."
    return PASS, f"both built for mode {c.mode()}", ""


@rule("SIZE-01", "The image fits what MCUboot can swap")
def _(c):
    limit, how = c.max_image()
    if limit is None:
        return UNKNOWN, f"Cannot work out the largest image: {how}.", ""
    out, status = [f"largest image MCUboot can swap: {limit} B = {how}"], PASS
    region = c.app.flash_region()
    hint = ""
    if c.image:
        size = c.image["image_size"]
        out.append(f"this image: {size} B ({100 * size / limit:.1f}%)")
        if size > limit:
            status, hint = FAIL, "The image builds, but MCUboot cannot swap it. Make it smaller or the slots larger."
    elif c.image_error:
        return FAIL, f"{c.image_path.name}: {c.image_error}.", "Pass zephyr.signed.bin, not zephyr.bin."
    else:
        out.append("no signed image found, size not checked")
    if c.app.on("OTA_KIT_SIZE_GUARD") and c.app.num("ROM_END_OFFSET", 0) and status == PASS:
        out.append("the kit's size guard stops the build above this limit (CONFIG_OTA_KIT_SIZE_GUARD=y)")
    elif region and region > c.app.partition("slot0_partition")[1] and status == PASS:
        # Seen on the ESP32: the linker region is the whole flash mapping, not the slot.
        status = UNKNOWN
        out.append(f"the linker region is {region} B, larger than slot 0: the linker script does not tie "
                   "the application to its slot, so this tool cannot tell how far it can grow")
        hint = "Nothing here stops an oversized build. Watch the image size yourself."
    elif region and region > limit and status == PASS:
        status = WARN
        out.append(f"the linker allows the application to grow to {region} B, {region - limit} B past that limit")
        hint = "A larger application would still build. Enable CONFIG_OTA_KIT_SIZE_GUARD, " \
               "or watch the size yourself."
    return status, "; ".join(out) + ".", hint


@rule("SIZE-02", "MCUboot fits its partition")
def _(c):
    if (r := need_boot(c)):
        return r
    part = c.boot.partition("boot_partition")
    if not part or not c.boot.bin.exists():
        return UNKNOWN, "boot_partition or MCUboot zephyr.bin not found.", ""
    used, size = c.boot.bin.stat().st_size, part[1]
    pct = 100 * used / size
    if used > size:
        return FAIL, f"MCUboot is {used} B, boot_partition is {size} B.", "Trim MCUboot, see BLOAT-01."
    if pct > 90:
        return WARN, f"MCUboot uses {used} of {size} B ({pct:.1f}%).", "Little room left, see BLOAT-01."
    return PASS, f"MCUboot uses {used} of {size} B ({pct:.1f}%)", ""


@rule("SIZE-03", "Oversized uploads are refused")
def _(c):
    if not c.app.on("MCUMGR_GRP_IMG"):
        return INFO, "The application has no MCUmgr image group.", ""
    if c.app.on("MCUMGR_GRP_IMG_TOO_LARGE_DISABLED"):
        return INFO, "CONFIG_MCUMGR_GRP_IMG_TOO_LARGE_DISABLED=y: the SMP server does not compare an " \
            "upload with what MCUboot can swap.", \
            "Optional: CONFIG_MCUMGR_GRP_IMG_TOO_LARGE_SYSBUILD=y. Not tested in this project."
    return PASS, "the SMP server checks the upload size against MCUboot's limit", ""


@rule("WDT-01", "MCUboot's watchdog timeout is within the hardware limit")
def _(c):
    if (r := need_boot(c)):
        return r
    b = c.boot
    if not (b.on("WATCHDOG") and b.on("BOOT_WATCHDOG_INSTALL_TIMEOUT_AT_BOOT")):
        return INFO, "MCUboot does not install a watchdog timeout in this build.", ""
    timeout = b.num("BOOT_WATCHDOG_TIMEOUT_MS")
    wdt = b.label(b.ref("aliases", "watchdog0") or "")
    key = (b.val("SOC_SERIES"), wdt.compat()[0] if wdt and wdt.compat() else None)
    if key not in WDT_MAX_MS:
        return UNKNOWN, f"MCUboot asks for {timeout} ms. No sourced limit for SoC series " \
            f"{key[0]} with watchdog {key[1]}.", \
            "Look up the largest timeout of this watchdog and compare it yourself."
    limit, source = WDT_MAX_MS[key]
    if timeout > limit:
        return FAIL, f"MCUboot asks for {timeout} ms, this watchdog can do at most {limit} ms ({source})", \
            "MCUboot then logs 'Watchdog install timeout failed: -22' and runs with no watchdog. " \
            "Set SB_CONFIG_OTA_KIT_MCUBOOT_WATCHDOG_TIMEOUT_MS below the limit."
    return PASS, f"MCUboot asks for {timeout} ms, limit {limit} ms", ""


@rule("WDT-02", "The application arms a watchdog with a sane timeout")
def _(c):
    a = c.app
    if not a.on("OTA_KIT"):
        return INFO, "CONFIG_OTA_KIT is off, the kit's watchdog is not in this image.", ""
    if not a.on("OTA_KIT_WATCHDOG"):
        return WARN, "CONFIG_OTA_KIT_WATCHDOG is off.", \
            "A test image that hangs is then only reverted after someone resets the board. " \
            "Give the board a watchdog0 alias."
    timeout, delay = a.num("OTA_KIT_WATCHDOG_TIMEOUT_MS"), a.num("OTA_KIT_HEALTH_DELAY_S")
    if timeout <= delay * 1000:
        return FAIL, f"Watchdog {timeout} ms fires before the health check at {delay} s.", "Raise the timeout."
    wdt = a.label(a.ref("aliases", "watchdog0") or "")
    key = (a.val("SOC_SERIES"), wdt.compat()[0] if wdt and wdt.compat() else None)
    if key not in WDT_MAX_MS:
        return UNKNOWN, f"Timeout {timeout} ms, health check at {delay} s. No sourced limit for " \
            f"SoC series {key[0]} with watchdog {key[1]}.", "Compare it with the watchdog's maximum yourself."
    if timeout > WDT_MAX_MS[key][0]:
        return FAIL, f"Timeout {timeout} ms is above the hardware limit {WDT_MAX_MS[key][0]} ms.", "Lower it."
    return PASS, f"timeout {timeout} ms, health check at {delay} s, limit {WDT_MAX_MS[key][0]} ms", ""


@rule("FLASH-01", "An external QSPI flash is reset at boot")
def _(c):
    out, status = [], PASS
    for name, img in (("application", c.app), ("MCUboot", c.boot)):
        if not img:
            continue
        p = img.partition("slot1_partition")
        flash = p[2] if p else None
        if not flash or "st,stm32-qspi-nor" not in flash.compat():
            continue
        if "reset-cmd" in flash.props:
            out.append(f"{name}: {flash.name} has reset-cmd, wait {flash.cells('reset-cmd-wait') or 'default'} us")
        else:
            status = FAIL
            out.append(f"{name}: {flash.name} has no reset-cmd")
    if not out:
        return INFO, "Slot 1 is not on an STM32 QSPI flash. Other external flash drivers are not checked.", \
            "If slot 1 is on another external flash, find out how it is reset after an MCU reset."
    hint = ""
    if status == FAIL:
        hint = "A reset during an erase leaves the flash busy. Measured: MCUboot aborts and the board is " \
               "dead for 30.6 s. Add reset-cmd and reset-cmd-wait for both images. PORTING.md step 3."
    return status, "; ".join(out) + ".", hint


@rule("SIG-01", "Images are signed, and not with a public development key")
def _(c):
    if (r := need_boot(c)):
        return r
    b = c.boot
    if b.on("BOOT_SIGNATURE_TYPE_NONE"):
        return FAIL, "CONFIG_BOOT_SIGNATURE_TYPE_NONE=y: MCUboot only checks a hash, anyone can make an image.", \
            "Select a signature type, the ota-kit snippet uses ECDSA P256."
    sig = next((k[len("CONFIG_BOOT_SIGNATURE_TYPE_"):] for k, v in b.config.items()
                if k.startswith("CONFIG_BOOT_SIGNATURE_TYPE_") and v == "y"), "unknown")
    key, app_key = b.val("BOOT_SIGNATURE_KEY_FILE", ""), c.app.val("MCUBOOT_SIGNATURE_KEY_FILE", "")
    out = [f"signature type {sig}, key file {Path(key).name or 'none'}"]
    if not key:
        return FAIL, "No signing key set for MCUboot.", "Pass -DSB_CONFIG_BOOT_SIGNATURE_KEY_FILE."
    first = key.split(",")[0]
    if Path(first).name in DEV_KEY_NAMES and "mcuboot" in Path(first).parts:
        status = FAIL if c.release else WARN
        return status, f"MCUboot is built with its bundled development key {Path(first).name}. " \
            "The private half of that key is public.", \
            "Generate your own key with imgtool keygen and pass it with -DSB_CONFIG_BOOT_SIGNATURE_KEY_FILE. " \
            + ("" if c.release else "This is a FAIL with --release.")
    if app_key and app_key != first:
        return FAIL, f"The application is signed with {app_key}, MCUboot verifies with {first}.", \
            "Set the key once, in sysbuild."
    if c.image:
        found = [TLV_SIG[t] for t in c.image["tlvs"] if t in TLV_SIG]
        if not found:
            return FAIL, f"{c.image_path.name} has no signature TLV.", "Sign it with the key MCUboot was built with."
        out.append(f"image carries a {found[0]} signature")
    out.append("that the key is the right one and kept private is not something this tool can see")
    return PASS, "; ".join(out), ""


@rule("SIG-02", "MCUboot checks the image in slot 0 at every boot")
def _(c):
    if (r := need_boot(c)):
        return r
    if c.boot.on("BOOT_VALIDATE_SLOT0"):
        return PASS, "CONFIG_BOOT_VALIDATE_SLOT0=y", ""
    return WARN, "CONFIG_BOOT_VALIDATE_SLOT0 is off: MCUboot verifies an update in slot 1, but boots " \
        "whatever is in slot 0 without a check. Measured on an ESP32: an image with 4 flipped bytes, " \
        "written straight to slot 0, was started.", \
        "Set CONFIG_BOOT_VALIDATE_SLOT0=y for MCUboot. Its ESP32 configuration turns it off, " \
        "the ota-kit snippet turns it back on."


@rule("DOWNGRADE-01", "Downgrade prevention")
def _(c):
    if (r := need_boot(c)):
        return r
    sw, hw = c.boot.on("MCUBOOT_DOWNGRADE_PREVENTION"), c.boot.on("MCUBOOT_HW_DOWNGRADE_PREVENTION")
    if sw or hw:
        kind = "security counter" if hw or c.boot.on("MCUBOOT_DOWNGRADE_PREVENTION_SECURITY_COUNTER") \
            else "image version"
        note = "" if c.app.on("MCUBOOT_BOOTLOADER_NO_DOWNGRADE") else \
            " The application was built without CONFIG_MCUBOOT_BOOTLOADER_NO_DOWNGRADE."
        return INFO, f"Downgrade prevention is on in MCUboot, by {kind}. An older image is refused at boot, " \
            f"not at upload.{note}", "It does not stop someone with a debug probe."
    return INFO, "Downgrade prevention is off: an older signed image is accepted.", \
        "Decide whether that is acceptable. With the kit: SB_CONFIG_OTA_KIT_DOWNGRADE_PREVENTION=y."


@rule("ENC-01", "Encrypted updates")
def _(c):
    if (r := need_boot(c)):
        return r
    b = c.boot
    if not b.on("BOOT_ENCRYPT_IMAGE"):
        return INFO, "Updates are not encrypted: the image is readable on the wire and in slot 1.", \
            "Optional. With the kit: ENC=1 scripts/build.sh. It protects the update file and an " \
            "external slot 1, not a device whose internal flash can be read."
    out, status, hint = ["MCUboot decrypts updates"], INFO, \
        "MCUboot holds the private key in its own flash. Anyone who can read the internal flash has it."
    key = b.val("BOOT_ENCRYPTION_KEY_FILE", "")
    if Path(key).name in DEV_ENC_KEY_NAMES and "mcuboot" in Path(key).parts:
        status = FAIL if c.release else WARN
        out.append(f"with MCUboot's bundled key {Path(key).name}, whose private half is public")
        hint = "Generate your own key with imgtool keygen and pass SB_CONFIG_BOOT_ENCRYPTION_KEY_FILE."
    s0, s1 = b.partition("slot0_partition"), b.partition("slot1_partition")
    if s0 and s1 and s0[2] is not s1[2] and not b.on("BOOT_SWAP_SAVE_ENCTLV"):
        status = WARN if status == INFO else status
        out.append("slot 1 is on another flash and CONFIG_BOOT_SWAP_SAVE_ENCTLV is off: MCUboot "
                   "writes the plain image key into the swap metadata there")
        hint = "Set CONFIG_BOOT_SWAP_SAVE_ENCTLV=y in MCUboot (MCUboot encrypted_images.md)."
    if c.image and not c.image["encrypted"]:
        out.append(f"{c.image_path.name} itself is not encrypted")
    out.append("a plain signed image is still accepted (seen on the board), encryption is not enforced")
    return status, "; ".join(out) + ".", hint


@rule("HEALTH-01", "The application registers a health check")
def _(c):
    a = c.app
    if not a.on("OTA_KIT"):
        return INFO, "CONFIG_OTA_KIT is off. Whether and how this application confirms an image is not checked.", ""
    if not a.map:
        return UNKNOWN, "No zephyr.map, cannot see whether ota_kit_set_health_check() is used.", ""
    head, _, kept = a.map.partition("Memory Configuration")
    discarded = head.partition("Discarded input sections")[2]
    # A function that is linked in has a line "<address> <name>" in the memory map part.
    if re.search(r"^\s+0x[0-9a-f]+\s+ota_kit_set_health_check\s*$", kept, flags=re.M):
        return PASS, "ota_kit_set_health_check() is linked in, so something calls it. " \
            "What the check tests is not visible to this tool", ""
    if ".text.ota_kit_set_health_check" in discarded:
        return FAIL, "ota_kit_set_health_check() was removed by the linker: nothing in the application calls it.", \
            "Without a registered check the kit never confirms, and every update is reverted. " \
            "Call ota_kit_set_health_check() in main()."
    return UNKNOWN, "ota_kit_set_health_check not found in the map file.", ""


@rule("HEALTH-02", "No forced failure or forced confirm in this build")
def _(c):
    out, status = [], PASS
    for opt in ("APP_HANG", "APP_HEALTH_FORCE_FAIL"):
        if c.app.on(opt):
            status = FAIL
            out.append(f"CONFIG_{opt}=y, this is a test image")
    if c.image and c.image["confirmed"]:
        status = FAIL if status == FAIL else WARN
        out.append(f"{c.image_path.name} is padded and already marked confirmed: it skips the test boot")
    if c.app.on("MCUMGR_GRP_IMG_ALLOW_CONFIRM_NON_ACTIVE_IMAGE_SECONDARY"):
        out.append("note: the SMP server lets a host confirm an uploaded image directly "
                   "(CONFIG_MCUMGR_GRP_IMG_ALLOW_CONFIRM_NON_ACTIVE_IMAGE_SECONDARY=y), which also skips the health check")
        status = INFO if status == PASS else status
    if status == PASS:
        return PASS, "no test options, image not pre-confirmed", ""
    hint = {FAIL: "Never ship a build with a forced failure option.",
            WARN: "Upload the plain zephyr.signed.bin, so the image has to earn its confirm.",
            INFO: "Use 'test', not 'confirm', from the host. scripts/ota_update.py does. Set the option to n to enforce it."}
    return status, "; ".join(out) + ".", hint[status]


@rule("BLE-01", "SMP over Bluetooth needs an encrypted link")
def _(c):
    a = c.app
    if not a.on("MCUMGR_TRANSPORT_BT"):
        return INFO, "SMP over Bluetooth is not in this build.", ""
    if a.on("MCUMGR_TRANSPORT_BT_PERM_RW"):
        return FAIL, "CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW=y: anyone in radio range can upload, erase slot 1 or reset.", \
            "Use CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_ENCRYPT or _AUTHEN. The ota-kit-ble snippet sets ENCRYPT."
    out, status, hint = [], PASS, ""
    if a.on("MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN"):
        out.append("encrypted and authenticated link required")
    else:
        out.append("encrypted link required. Pairing can still be 'Just Works', which does not prove who the central is")
    if not a.on("BT_SETTINGS"):
        status, hint = WARN, "Enable CONFIG_BT_SETTINGS, or the host has to pair again after every reset."
        out.append("bonds are not stored (CONFIG_BT_SETTINGS off)")
    elif a.on("OTA_KIT_TRANSPORT_BLE") and not a.on("OTA_KIT_BLE_DEVICE_ADDR_FROM_CHIP_ID") and not a.on("BT_PRIVACY"):
        status, hint = WARN, "Seen on the board: the address changed at every boot and the bond was useless. " \
            "Keep CONFIG_OTA_KIT_BLE_DEVICE_ADDR_FROM_CHIP_ID=y or give the device a stable identity."
        out.append("no fixed address and no privacy: the stored bond may not survive a reset")
    if a.on("BT_SETTINGS") and not a.partition("storage_partition"):
        status, hint = WARN, "Add a storage_partition for the settings backend."
        out.append("no storage_partition for the bonds")
    return status, "; ".join(out) + ".", hint


@rule("UART-01", "SMP over UART")
def _(c):
    if not c.app.on("MCUMGR_TRANSPORT_UART"):
        return INFO, "SMP over UART is not in this build.", ""
    return INFO, "SMP over UART has no authentication: anyone on the port can upload, erase slot 1 or reset. " \
        "An unsigned image still does not boot.", "Fine on a bench. Decide whether the port is reachable in the product."


@rule("BLOAT-01", "MCUboot options that cost flash")
def _(c):
    if (r := need_boot(c)):
        return r
    b, out = c.boot, []
    for opt, why in (("MCUBOOT_VERIFY_LOGICAL_SECTORS", "checks and logs every sector at boot. Measured here: +1116 B and a slow boot"),
                     ("MCUBOOT_LOG_LEVEL_DBG", "debug logging"), ("LOG_MODE_DEFERRED", "deferred logging with its own thread"),
                     ("LOG_MODE_IMMEDIATE", "immediate logging"), ("MCUBOOT_SERIAL", "serial recovery"),
                     ("ASSERT", "assertions"), ("DEBUG", "debug build"), ("NO_OPTIMIZATIONS", "no optimisation"),
                     ("DEBUG_OPTIMIZATIONS", "debug optimisation level"), ("SHELL", "shell"),
                     ("BOOT_USE_BENCH", "benchmark code")):
        if b.on(opt):
            out.append(f"CONFIG_{opt}=y ({why})")
    if b.on("LOG") and not b.on("LOG_MODE_MINIMAL") and not any("LOG_MODE" in x for x in out):
        out.append("CONFIG_LOG=y without CONFIG_LOG_MODE_MINIMAL")
    if out:
        return WARN, "; ".join(out) + ".", "Turn these off for a release build of MCUboot."
    return PASS, "none of the known size options are on" + \
        (" (logging is in minimal mode)" if b.on("LOG_MODE_MINIMAL") else ""), ""


# ---------- report

def run(build_dir, image=None, release=False, erase_sizes=(None, None)):
    ctx = Ctx(build_dir, image, release, erase_sizes)
    findings = []
    for rule_id, title, fn in RULES:
        try:
            status, evidence, hint = fn(ctx)
        except Exception as e:  # a rule that cannot read its input must not hide the others
            status, evidence, hint = UNKNOWN, f"rule could not run: {type(e).__name__}: {e}", ""
        findings.append({"id": rule_id, "status": status, "title": title, "evidence": evidence, "hint": hint})
    return ctx, findings


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("build_dir")
    ap.add_argument("--image", help="signed image to check, default <app>/zephyr/zephyr.signed.bin")
    ap.add_argument("--json", help="also write the findings to this file")
    ap.add_argument("--release", action="store_true", help="treat a development signing key as FAIL")
    for slot in (0, 1):
        ap.add_argument(f"--slot{slot}-erase-size", type=lambda x: int(x, 0), metavar="BYTES",
                        help=f"erase size of the slot {slot} flash from its datasheet, "
                             "used only when the devicetree does not give it")
    args = ap.parse_args()

    ctx, findings = run(args.build_dir, args.image, args.release,
                        (args.slot0_erase_size, args.slot1_erase_size))
    print(f"OTA doctor: {args.build_dir}")
    print(f"  application: {ctx.app.val('BOARD_TARGET', '?')}, MCUboot build: "
          f"{'found' if ctx.boot else 'not found'}, image: {ctx.image_path or 'none'}\n")
    for f in findings:
        print(f"[{f['status']:7}] {f['id']:12} {f['title']}")
        print(f"            {f['evidence']}")
        if f["hint"]:
            print(f"            fix: {f['hint']}")
    count = {s: sum(f["status"] == s for f in findings) for s in (PASS, INFO, WARN, FAIL, UNKNOWN)}
    print("\n" + ", ".join(f"{n} {s}" for s, n in count.items()))
    print("UNKNOWN means the tool could not judge. No FAIL does not prove the board is safe.")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"build_dir": str(args.build_dir), "image": str(ctx.image_path or ""),
             "summary": count, "findings": findings}, indent=2) + "\n")
    return 1 if count[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
