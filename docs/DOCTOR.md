# OTA doctor

A host tool that reads a finished build and warns about OTA configuration mistakes before anything is flashed.

```sh
scripts/ota_doctor.py build/v1.0.0
scripts/ota_doctor.py build/v1.0.0 --json report.json --release
scripts/ota_doctor.py build/v1.0.0 --slot1-erase-size 4096      # value from the flash datasheet
```

**A report without FAIL does not prove the board is safe.**
The tool checks a list of known mistakes in the build output. It does not run the firmware, does not check signatures, and cannot see mistakes nobody has taught it. See "Limits" below.

## Inputs

| Input | Used for |
|---|---|
| `domains.yaml` in the sysbuild build directory | finding the application and MCUboot builds |
| `zephyr/.config` of both images | every option check |
| `zephyr/zephyr.dts` of both images | partitions, flash nodes, watchdog, code partition |
| `zephyr/zephyr.map` of the application | linker FLASH region, whether the health check is called |
| `zephyr/zephyr.bin` of MCUboot | its size |
| `zephyr/zephyr.signed.bin`, or `--image FILE` | header, size, signature TLV, confirmed flag |

Python standard library only. The devicetree is read with a small parser for the generated `zephyr.dts`, so the tool needs neither Zephyr nor its Python packages. Tested with Python 3.12.

## Output

- Text report: one block per rule with a status, the evidence, and a fix hint.
- `--json FILE`: the same findings for CI.
- Exit code 1 if any rule reports FAIL, else 0.

| Status | Meaning |
|---|---|
| PASS | The rule was checked and holds |
| INFO | A fact worth knowing, no action required by the tool |
| WARN | Probably a problem, or a check that could only be done in part |
| FAIL | A known mistake. Exit code 1 |
| UNKNOWN | The tool could not judge. Treat it as "check this yourself", not as a pass |

`--release` turns a development signing key from WARN into FAIL.

## Rules

"Seen" means the problem happened on `disco_l475_iot1` in this project. "Docs" means the rule comes from MCUboot or Zephyr documentation or source, in the versions named in `docs/SETUP.md`.

| ID | Checks | Worst status | Evidence |
|---|---|---|---|
| LAYOUT-01 | `boot_partition`, `slot0_partition`, `slot1_partition` exist | FAIL | Docs: Zephyr sysbuild Kconfig, "MCUboot expects slot0_partition and slot1_partition to be present in DT" |
| LAYOUT-02 | The application is linked into slot 0 and MCUboot into the boot partition | FAIL | Seen in the first bring-up: an MCUboot overlay replaced the stock one, and MCUboot was linked into slot 0. The build did not complain |
| LAYOUT-03 | Both images have the same partition offsets and sizes | FAIL | Seen as a near miss: the slot 0 resize has to reach both images. Docs: PORTING.md step 6 |
| SECTOR-01 | Both slots use one sector size, or a logical sector size that fits both | FAIL | Seen in the first bring-up: 2 K pages against 4 K sectors. Docs: MCUboot `swap_move.c`, "Cannot upgrade: not same sector layout" |
| SECTOR-02 | Slot offsets and sizes are whole multiples of the sector size | FAIL | Docs: MCUboot Kconfig help for `MCUBOOT_LOGICAL_SECTOR_SIZE`, "aligned to hardware sectors in size and alignment". Fixture built, not flashed |
| SECTOR-03 | Sector counts fit the swap mode, and stay under `BOOT_MAX_IMG_SECTORS` | FAIL | Docs: MCUboot `swap_move.c` and `swap_offset.c`, "not a compatible amount of sectors", "more sectors than allowed" |
| SWAP-01 | A scratch partition exists when swap using scratch is selected | FAIL | Docs: sysbuild Kconfig help for `MCUBOOT_MODE_SWAP_SCRATCH` |
| SWAP-02 | The application was built for the mode MCUboot runs | FAIL | Docs: Zephyr `modules/Kconfig.mcuboot`, the application side mode options |
| SIZE-01 | The signed image is not larger than MCUboot can swap. Reports whether the kit's size guard is on | FAIL | Seen in the first doctor runs, see below. Docs: MCUboot `design.md`, maximum image size formulas |
| SIZE-02 | MCUboot fits the boot partition, warning above 90% | FAIL | Docs. MCUboot is at 61.6% here, the limit was never hit |
| SIZE-03 | Whether the SMP server refuses oversized uploads | INFO | Docs: Zephyr `MCUMGR_GRP_IMG_TOO_LARGE_CHECK`. The option was not tested here |
| WDT-01 | MCUboot's watchdog timeout is within the hardware limit | FAIL | Seen in the failure handling tests: 300 s on an STM32L4, error -22, MCUboot ran with no watchdog |
| WDT-02 | The application arms a watchdog, with a timeout above the health delay and within the limit | FAIL | Seen in the failure handling tests. The kit also checks the first part at build time |
| FLASH-01 | An STM32 QSPI flash holding slot 1 has `reset-cmd`, in both images | FAIL | Seen in the QSPI reset fix: a reset during an erase left the board dead for 30.6 s |
| SIG-01 | A signature type is selected, a key is set, it is not one of MCUboot's bundled keys, both images use the same key, the image carries a signature TLV | FAIL | Docs: MCUboot `readme-zephyr.md`, the bundled keys "should never be used for production, since the private key is publicly available". Seen: the minimal sample builds with that key when none is passed |
| SIG-02 | MCUboot has `CONFIG_BOOT_VALIDATE_SLOT0=y` | WARN | Seen in the first ESP32 trial on an ESP32: MCUboot's `socs/esp32_procpu.conf` turns it off, and a corrupted image written straight to slot 0 was started. See [BOARD_ESP32.md](BOARD_ESP32.md) |
| DOWNGRADE-01 | Reports whether downgrade prevention is on, and that it acts at boot | INFO | Docs: MCUboot Kconfig `MCUBOOT_DOWNGRADE_PREVENTION`, `MCUBOOT_HW_DOWNGRADE_PREVENTION`. Seen in the final firmware series: rejected at boot, not at upload |
| ENC-01 | Reports whether updates are encrypted. Warns about a bundled encryption key, and about a plain image key in swap metadata on an external flash | FAIL with `--release` | Docs: MCUboot `encrypted_images.md` and Kconfig help of `BOOT_SWAP_SAVE_ENCTLV`. Seen in the final firmware series: a plain image is still accepted |
| HEALTH-01 | Something in the application calls `ota_kit_set_health_check()` | FAIL | By design of the kit: no check, no confirm, every update is reverted. Fixture built, not flashed |
| HEALTH-02 | No forced failure options, image not built as already confirmed. Notes when a host may confirm directly | FAIL | Seen: the test options exist in the example application. Docs: imgtool `--confirm`, Zephyr `MCUMGR_GRP_IMG_ALLOW_CONFIRM_NON_ACTIVE_IMAGE_SECONDARY` |
| BLE-01 | SMP over Bluetooth requires an encrypted link, bonds are stored, the address is stable | FAIL | Seen in the first BLE series: the spike had no encryption, and bonds were lost at every reset until the address was fixed |
| UART-01 | Notes that SMP over UART has no authentication | INFO | Docs and design: there is none in the transport |
| BLOAT-01 | MCUboot options that cost flash | WARN | Seen: `MCUBOOT_VERIFY_LOGICAL_SECTORS` cost 1116 B and a slow boot. The other options on the list come from their Kconfig descriptions, their cost was not measured |

### SIZE-01, the one rule the doctor found first

The linker lets the application grow to the slot 0 size minus a trailer estimate: 880490 B on this board.
MCUboot's documented limit for swap using move is `(N - 1) x sector size - trailer`, with N the number of sectors in slot 0: 876544 B.
So there is a gap of 3946 B in which an image builds, signs and uploads, and cannot be swapped.

Tested on the board with an image of 879091 B, inside that gap:

```
upload done in 140.10 s (6275 B/s)
slot 1 v1.4.0 marked for test
I: Image index: 0, Swap type: test
E: Image in the secondary slot is not valid!
I: Image version: v1.0.0
```

A correctly signed image was refused because of its size. The board kept running the old version, so nothing was lost but the 140 s upload.
Since the final firmware series the kit stops such a build with a linker assert (`CONFIG_OTA_KIT_SIZE_GUARD`), and an image 17 B under the limit was shown to swap. The `image_too_big` fixture is a build from before the guard.
The doctor reported FAIL for that image before it was uploaded.
The same 3946 B gap showed in the nRF52840 sample build before the guard. It was not tested on that board.

## Watchdog limits

The tool only compares a timeout against a limit that has a source. Everything else is UNKNOWN.

| SoC series | Watchdog | Largest timeout | Source |
|---|---|---|---|
| `stm32l4x` | `st,stm32-watchdog` (IWDG) | 32768 ms | Prescaler 256 x (reload 0xFFF + 1) / LSI 32000 Hz. Constants read from Zephyr `drivers/watchdog/wdt_iwdg_stm32.c` and the STM32L4 HAL headers (`LSI_VALUE`, `IWDG_RLR_RL`, no /1024 prescaler). Confirmed on the board: 300000 ms refused, 30000 ms accepted |
| anything else | | unknown | no source checked |

The ST reference manual was not read for this. Add a row only with a source.

## Tests

```sh
python3 -m unittest discover -s tests/doctor -v
```

No hardware and no Zephyr are needed. `.github/workflows/ci.yml` runs the same command on every push, and `tests/check_paths.py`, which fails if a tracked file or a fixture contains a home directory path.
The fixtures were captured in the first doctor runs and the final firmware series. The bad ones are from before the size guard and downgrade prevention existed, which does not affect the rule each one tests.

Each fixture in `tests/doctor/fixtures/` is a capture of a real build, made by `tests/doctor/capture.py`: the `.config` and `zephyr.dts` files unchanged, the map file cut down, binaries reduced to what the doctor reads.
The bad ones are the good configuration with one mistake put back in.

| Fixture | How it was built | Expected finding | Result |
|---|---|---|---|
| `good_uart` | `scripts/build.sh 1.0.0`, final firmware | no FAIL | no FAIL, WARN on SECTOR-01 |
| `good_ble` | `VARIANT=ble scripts/build.sh 1.0.0`, final firmware | no FAIL, BLE-01 PASS | as expected |
| `good_encrypted` | `ENC=1 scripts/build.sh 1.0.0` | no FAIL, ENC-01 reports encryption | as expected |
| `nrf52840dk_sample` | `samples/minimal` for `nrf52840dk/nrf52840`, sysbuild, `-S ota-kit` | see below | no FAIL |
| `wdt_300s` | `-DSB_CONFIG_OTA_KIT_MCUBOOT_WATCHDOG_TIMEOUT_MS=0` | WDT-01 FAIL | FAIL |
| `no_reset_cmd` | overlay deleting `reset-cmd` in both images | FLASH-01 FAIL | FAIL |
| `misaligned_slot` | overlay, slot 0 = 866 K | SECTOR-02 FAIL | FAIL |
| `mcuboot_in_slot0` | an MCUboot overlay that replaces the stock one | LAYOUT-02 FAIL | FAIL |
| `image_too_big` | `-DCONFIG_APP_PAD_BYTES=831100`, image 879091 B | SIZE-01 FAIL | FAIL, and refused by MCUboot on the board |
| `ble_no_encryption` | BLE build with `-DCONFIG_MCUMGR_TRANSPORT_BT_PERM_RW=y` | BLE-01 FAIL | FAIL |
| `no_health_check` | the sample with the `ota_kit_set_health_check()` call removed | HEALTH-01 FAIL | FAIL |
| `dev_key` | built with MCUboot's `root-ec-p256.pem` | SIG-01 WARN, FAIL with `--release` | as expected |
| `preconfirmed_image` | `imgtool sign --pad --confirm` | HEALTH-02 WARN | WARN |
| `esp32_default` | `samples/minimal` for `esp32_devkitc/esp32/procpu`, built before the kit turned slot 0 validation back on | SIG-02 WARN, SIZE-01 and WDT-02 UNKNOWN | as expected |
| `esp32_kit` | the example app for the same board, current kit | SIG-02 PASS, SIZE-01 and WDT-02 UNKNOWN | as expected |
| `no_logical_sectors` | `-DSB_CONFIG_OTA_KIT_MCUBOOT_LOGICAL_SECTOR_SIZE=0x0` | see below | UNKNOWN on four rules |

Two results that are not a clean catch:

- **`no_logical_sectors` is our first real bug, and the tool cannot see it by itself.** The erase size of the QSPI flash is not in the devicetree, the driver reads it from the chip at run time. So SECTOR-01 says UNKNOWN, not FAIL. With `--slot1-erase-size 4096` from the datasheet it says FAIL. The good build has the same blind spot, which is why SECTOR-01 is a WARN there.
- **On the ESP32 two rules stay UNKNOWN.** WDT-02 has no sourced watchdog limit for that SoC. SIZE-01 can check the image against the swap limit, but the ESP32 linker region is the whole 4 MB mapping, so the tool cannot say how far the application can grow. No limit was added without a source.
- **The good builds carry one WARN**, SECTOR-01, for the reason above. Until the final firmware series they also had SIZE-01 for the 3946 B gap, which the size guard now closes, in the nRF sample build as well.

### The nRF52840 sample build

Compile only, never flashed. Summary with the final module: 12 PASS, 8 INFO, 1 WARN, 0 FAIL, 1 UNKNOWN.

| Rule | Status | What it said |
|---|---|---|
| SIZE-01 | PASS | Limit 471040 B, size guard on. In the first doctor runs, before the guard, this was a WARN for the same 3946 B gap as on the STM32 board |
| SIG-01 | WARN | Built with MCUboot's bundled `root-ec-p256.pem`. True: the sample command line passes no key |
| WDT-02 | UNKNOWN | Timeout 10000 ms, no sourced limit for series `nrf52` with `nordic,nrf-wdt` |
| WDT-01 | INFO | MCUboot does not install a watchdog timeout in this build. Whether MCUboot feeds the nRF watchdog some other way was not checked |
| FLASH-01 | INFO | Slot 1 is not on an STM32 QSPI flash. Other external flashes are not checked |

Rules it could not really judge there: WDT-02 (no limit), WDT-01 (only knows the option is off), FLASH-01 (only knows the STM32 QSPI driver).
The PASS results on that board are checks of the build files only. Nothing about that board was verified on hardware.

## Limits

- **It reads a build, not a board.** Option bytes, readout protection, the real flash chip, the real watchdog are not seen.
- **No cryptography.** It sees that a signature TLV exists. It does not verify the signature or match it to the key.
- **It cannot tell whether your key is private.** Only that it is not one of MCUboot's bundled keys, by file name and path.
- **The health check rule sees a call, not its quality.** A check that always returns true passes.
- **Erase sizes of external flashes are often not in the devicetree.** Pass them with `--slot1-erase-size`, or SECTOR-01 to SECTOR-03 and SIZE-01 may say UNKNOWN.
- **The trailer size comes from Zephyr's own estimate** (`CONFIG_MCUBOOT_UPDATE_FOOTER_SIZE`). If that is 0, SIZE-01 says UNKNOWN. Encrypted images were never built here.
- **Swap using move is the only mode with a hardware tested rule.** Scratch, offset and overwrite rules come from documentation only. Direct XIP and RAM load have no size rule.
- **Watchdog limits: one SoC series.** Every other series is UNKNOWN.
- **FLASH-01 knows one driver**, `st,stm32-qspi-nor`.
- **Multi image builds** (more than one application image) were never tried.
- **The devicetree parser** is written for the generated `zephyr.dts` of these builds. An unusual construct could be misread, which would show as a wrong or UNKNOWN finding.
- **Rules from documentation** were checked against MCUboot `v2.4.0-118` and Zephyr `v4.4.0-13485`. Other versions may differ.
- **One board on hardware.** Every "seen" rule was seen on `disco_l475_iot1` only.
