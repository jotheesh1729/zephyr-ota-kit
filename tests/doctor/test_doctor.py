#!/usr/bin/env python3
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/ota_doctor.py. No hardware and no Zephyr needed.

Usage: python3 -m unittest discover -s tests/doctor -v

Each fixture is a capture of a real build (see capture.py and docs/DOCTOR.md), made from the
good configuration with one mistake put back in. The test checks that the doctor reports
exactly that mistake, and does not start reporting FAIL on the good builds.
"""
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ota_doctor  # noqa: E402

# fixture -> (extra arguments for run(), {rule: expected status}, rules allowed to FAIL)
# "good" fixtures list the statuses that are not PASS or INFO, so a new WARN shows up as a test failure.
CASES = {
    "good_uart": ({}, {"SECTOR-01": "WARN", "SIZE-01": "PASS"}, set()),
    "good_ble": ({}, {"SECTOR-01": "WARN", "SIZE-01": "PASS", "BLE-01": "PASS"}, set()),
    "good_encrypted": ({}, {"SECTOR-01": "WARN", "SIZE-01": "PASS", "ENC-01": "INFO"}, set()),
    "nrf52840dk_sample": ({}, {"SIZE-01": "PASS", "WDT-02": "UNKNOWN", "SIG-01": "WARN"}, set()),
    # ESP32: no sourced watchdog limit, and the linker region is not the slot. Both must stay UNKNOWN.
    "esp32_kit": ({}, {"SIG-02": "PASS", "SIZE-01": "UNKNOWN", "WDT-02": "UNKNOWN"}, set()),
    # the minimal sample for the ESP32, built before the kit turned slot 0 validation back on
    "esp32_default": ({}, {"SIG-02": "WARN", "SIZE-01": "UNKNOWN", "WDT-02": "UNKNOWN"}, set()),
    # real bugs, put back one at a time
    "wdt_300s": ({}, {"WDT-01": "FAIL"}, {"WDT-01"}),
    "no_reset_cmd": ({}, {"FLASH-01": "FAIL"}, {"FLASH-01"}),
    "misaligned_slot": ({}, {"SECTOR-02": "FAIL"}, {"SECTOR-02"}),
    "mcuboot_in_slot0": ({}, {"LAYOUT-02": "FAIL"}, {"LAYOUT-02"}),
    "image_too_big": ({}, {"SIZE-01": "FAIL"}, {"SIZE-01"}),
    "ble_no_encryption": ({}, {"BLE-01": "FAIL"}, {"BLE-01"}),
    "no_health_check": ({}, {"HEALTH-01": "FAIL"}, {"HEALTH-01"}),
    "dev_key": ({}, {"SIG-01": "WARN"}, set()),
    "preconfirmed_image": ({}, {"HEALTH-02": "WARN"}, set()),
    # the devicetree does not give the erase size of the QSPI flash: the tool must say so, not guess
    "no_logical_sectors": ({}, {"SECTOR-01": "UNKNOWN", "SECTOR-02": "UNKNOWN",
                                "SECTOR-03": "UNKNOWN", "SIZE-01": "UNKNOWN"}, set()),
}


class DoctorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        for f in (HERE / "fixtures").glob("*.tar.gz"):
            with tarfile.open(f) as tar:
                tar.extractall(Path(cls.tmp.name) / f.name[:-len(".tar.gz")], filter="data")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def findings(self, name, **kw):
        _, found = ota_doctor.run(Path(self.tmp.name) / name, **kw)
        return {f["id"]: f["status"] for f in found}

    def test_every_fixture_has_a_case(self):
        self.assertEqual(sorted(CASES), sorted(p.name for p in Path(self.tmp.name).iterdir()))

    def test_fixtures(self):
        for name, (kw, expected, may_fail) in CASES.items():
            with self.subTest(fixture=name):
                got = self.findings(name, **kw)
                for rule, status in expected.items():
                    self.assertEqual(got[rule], status, f"{name}: {rule}")
                fails = {r for r, s in got.items() if s == "FAIL"}
                self.assertEqual(fails, may_fail, f"{name}: unexpected FAIL set")

    def test_good_builds_have_no_other_warnings(self):
        for name in ("good_uart", "good_ble", "good_encrypted", "nrf52840dk_sample"):
            with self.subTest(fixture=name):
                got = self.findings(name)
                noisy = {r: s for r, s in got.items() if s in ("WARN", "FAIL", "UNKNOWN")}
                self.assertEqual(noisy, {r: s for r, s in CASES[name][1].items()
                                         if s in ("WARN", "FAIL", "UNKNOWN")})

    def test_datasheet_erase_size_turns_unknown_into_a_verdict(self):
        """Our first real bug: 2 K pages against 4 K sectors with no logical sector size."""
        got = self.findings("no_logical_sectors", erase_sizes=(None, 4096))
        self.assertEqual(got["SECTOR-01"], "FAIL")
        got = self.findings("good_uart", erase_sizes=(None, 4096))
        self.assertEqual(got["SECTOR-01"], "PASS")

    def test_release_mode_fails_on_a_development_key(self):
        self.assertEqual(self.findings("dev_key", release=True)["SIG-01"], "FAIL")
        self.assertEqual(self.findings("good_uart", release=True)["SIG-01"], "PASS")

    def test_exit_code_and_json(self):
        cli = [sys.executable, str(ROOT / "scripts/ota_doctor.py")]
        out = Path(self.tmp.name) / "report.json"
        bad = subprocess.run(cli + [str(Path(self.tmp.name) / "wdt_300s"), "--json", str(out)],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("[FAIL", bad.stdout)
        report = json.loads(out.read_text())
        self.assertEqual(report["summary"]["FAIL"], 1)
        self.assertEqual({f["id"] for f in report["findings"] if f["status"] == "FAIL"}, {"WDT-01"})
        good = subprocess.run(cli + [str(Path(self.tmp.name) / "good_uart")], capture_output=True)
        self.assertEqual(good.returncode, 0)

    def test_settings_are_reported(self):
        """Downgrade prevention and encryption are facts to report, not pass or fail."""
        _, found = ota_doctor.run(Path(self.tmp.name) / "good_uart")
        text = {f["id"]: f["evidence"] for f in found}
        self.assertIn("Downgrade prevention is on", text["DOWNGRADE-01"])
        self.assertIn("not encrypted", text["ENC-01"])
        self.assertIn("size guard", text["SIZE-01"])
        _, found = ota_doctor.run(Path(self.tmp.name) / "good_encrypted")
        text = {f["id"]: f["evidence"] for f in found}
        self.assertIn("MCUboot decrypts updates", text["ENC-01"])
        _, found = ota_doctor.run(Path(self.tmp.name) / "image_too_big")  # built before the guard existed
        self.assertIn("Downgrade prevention is off", {f["id"]: f["evidence"] for f in found}["DOWNGRADE-01"])

    def test_slot0_validation(self):
        """MCUboot's ESP32 configuration turns the check of slot 0 off. Every other fixture has it on."""
        for name in CASES:
            with self.subTest(fixture=name):
                self.assertEqual(self.findings(name)["SIG-02"],
                                 "WARN" if name == "esp32_default" else "PASS")

    def test_raw_binary_is_not_an_image(self):
        raw = Path(self.tmp.name) / "raw.bin"
        raw.write_bytes(bytes(2048))
        got = self.findings("good_uart", image=str(raw))
        self.assertEqual(got["SIZE-01"], "FAIL")


if __name__ == "__main__":
    unittest.main()
