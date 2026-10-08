# Setup

Checked on 2026-10-05. Host: Pop!_OS, an Ubuntu 24.04 based Linux distribution, x86-64.

## Found (nothing reinstalled)

| Item | Value |
|---|---|
| Zephyr workspace | `~/zephyrproject` |
| Zephyr | `v4.4.0-13485-g133c2eb7d3c` (4.4.99, main) |
| MCUboot | `v2.4.0-118-g7ad67106` at `bootloader/mcuboot` |
| west | 1.5.0, inside `~/zephyrproject/.venv` only |
| Python | 3.12.3 (venv) |
| Zephyr SDK | 1.0.1 at `~/zephyr-sdk-1.0.1`, `arm-zephyr-eabi` present |
| imgtool | 2.4.0 (venv) |
| OpenOCD | 0.12.0 at `/usr/bin/openocd` |
| st-flash | `/usr/bin/st-flash` |
| pyocd | 0.45.1 (venv) |
| pyserial | 3.5 (venv) |
| udev rules | `/etc/udev/rules.d/60-openocd.rules` |
| Groups | user is in `dialout` and `plugdev` |

Not set, and not needed: `ZEPHYR_BASE`, `ZEPHYR_SDK_INSTALL_DIR`.
west finds Zephyr from the workspace. CMake finds the SDK from `~/.cmake/packages`.

## Missing

| Item | Action |
|---|---|
| `mcumgr` CLI (needs Go) | Skipped. Using the Python SMP client instead. |
| `smpclient` | Installed 7.3.0 into the venv (`pip install smpclient`). |
| STM32CubeProgrammer | Skipped. It is the board's default flash runner, so flash with `--runner openocd`. |

## Every shell

```sh
source ~/zephyrproject/.venv/bin/activate
```

`west` and `imgtool` do not exist outside this venv.

## Blinky

`$OTA_KIT` in the commands on this page is the directory of your clone of this repository.

Build (worked):

```sh
cd ~/zephyrproject
west build -p always -b disco_l475_iot1 \
  -d "$OTA_KIT/build/blinky" \
  zephyr/samples/basic/blinky
```

Result: FLASH 18840 B of 1 MB (1.80%), RAM 4608 B of 96 KB (4.69%).

Flash (worked):

```sh
west flash -d "$OTA_KIT/build/blinky" --runner openocd
```

Result: wrote 18840 bytes in 0.56 s. Probe is ST-LINK/V2.1 (`0483:374b`), firmware V2J40M27.
Target is STM32L475, 1024 KiB flash, RDP level 0.

Serial console: USART1 through the ST-LINK VCP, 115200 8N1, at `/dev/ttyACM0`.
Verified by reading `LED state: ON` / `LED state: OFF` lines from the port.

LD2 blinking by eye: DONE. Confirmed by a person on 2026-10-05.

## Board facts that matter later

From `zephyr/boards/st/disco_l475_iot1/disco_l475_iot1.dts`:

- `boot_partition` 0x00000, 64 K, internal flash
- `slot0_partition` 0x10000, 928 K, internal flash
- `storage_partition` 0xF8000, 32 K, internal flash
- `slot1_partition` 0x000000, 864 K, external QSPI flash (MX25R6435F)
- No scratch partition

Slot 1 is on external flash and is smaller than slot 0. The MCUboot setup below has to handle that.

# MCUboot boot

## Result

Signed v1.0.0 boots through MCUboot on the board. Serial log:

```
I: Starting bootloader
I: Primary image: magic=unset, swap_type=0x1, copy_done=0x3, image_ok=0x3
I: Secondary image: magic=unset, swap_type=0x1, copy_done=0x3, image_ok=0x3
I: Image index: 0, Swap type: none
I: Bootloader chainload address offset: 0x10000
I: Image version: v1.0.0
I: Jumping to the first image slot
*** Booting Zephyr OS build v4.4.0-13485-g133c2eb7d3cb ***
OTA app v1.0.0, blink 1000 ms
```

## Flash layout

```
Internal flash, STM32L475, 1 MB, 2 K pages (base 0x08000000)

0x00000 +---------------------------+
        | boot_partition    64 K    |  MCUboot (40368 B used)
0x10000 +---------------------------+
        | slot0_partition  868 K    |  running image (primary)
        | 217 sectors of 4 K        |
0xE9000 +---------------------------+
        | unused            60 K    |  freed by the slot 0 resize
0xF8000 +---------------------------+
        | storage_partition 32 K    |
0x100000+---------------------------+

External QSPI flash, MX25R6435F, 8 MB, 4 K sectors

0x000000 +--------------------------+
         | slot1_partition  864 K   |  staged update (secondary)
         | 216 sectors of 4 K       |
0x0D8000 +--------------------------+
         | slot2_partition    7 M   |  unused by this project
0x7D8000 +--------------------------+
```

No scratch partition. Swap using move does not need one.

## Layout decision

Kept: swap using move, slot 1 on QSPI. No fallback was needed.

| Fallback trigger | Outcome |
|---|---|
| MCUboot over 64 K | No. 40208 B, 61.35% of 64 K. No trimming needed. |
| Sector errors needing more than one fix | No. One fix, described below. |
| QSPI driver fails in bootloader | No. MCUboot read and verified all 216 slot 1 sectors. |

The one sector fix:

- Internal flash erases in 2 K pages. QSPI erases in 4 K sectors.
- Swap using move needs equal sector sizes, and slot 0 one sector bigger than slot 1.
- `CONFIG_MCUBOOT_LOGICAL_SECTOR_SIZE=0x1000` makes MCUboot treat both as 4 K sectors.
- An overlay shrinks slot 0 from 928 K to 868 K, so it has 217 sectors against 216.
- Cost: 60 K of internal flash is unused. The option is marked experimental in MCUboot.

## Sizes (from build output)

| Image | Flash | RAM |
|---|---|---|
| MCUboot | 40208 B of 64 K (61.35%) | 15552 B of 96 K (15.82%) |
| App v1.0.0 | 19984 B | 4608 B |
| Signed app `zephyr.signed.bin` | 20136 B | |

## Timing

- Boot, no swap: about 0.4 s from MCUboot banner to app banner. Host side timestamps, 200 ms resolution.
- Swap time: 4.5 s for a 46.9 K image (2 runs: 4.53 s, 4.48 s). Measured in the first upload and swap as MCUboot start to app jump, so it includes image verification. Host side timestamps.

## Signing

- Key: ECDSA P256, `keys/ota_signing.pem`, gitignored. Public half is `keys/ota_signing.pub.pem`.
- `imgtool verify` with our public key: image validated.
- `imgtool verify` with the MCUboot default key: "No signature found for the given key".
- MCUboot verifies with tinycrypt.

## Commands that worked

```sh
source ~/zephyrproject/.venv/bin/activate
imgtool keygen -k keys/ota_signing.pem -t ecdsa-p256
imgtool getpub -k keys/ota_signing.pem -e pem -o keys/ota_signing.pub.pem
scripts/build.sh 1.0.0 -p always
(cd ~/zephyrproject && west flash -d "$OTA_KIT/build/v1.0.0" --runner openocd)
```

## Errors hit and fixes

- `west: unknown command "build"`: west build only works inside the workspace. `scripts/build.sh` changes into it first.
- `app_version.h: No such file`: the header is `<zephyr/app_version.h>`.
- MCUboot linked into slot 0 (region showed 868 K): `sysbuild/mcuboot.overlay` replaces MCUboot's own `app.overlay`. Added `zephyr,code-partition = &boot_partition` to ours.

## Open items

- `E: Watchdog install timeout failed: -22` at MCUboot start. Resolved in the failure handling tests: MCUboot asked for 300 s and the IWDG maximum is about 32.8 s. Now set to 30 s. See the Watchdog section in `docs/RESULTS.md`.
- Build warning about `MCUBOOT_UPDATE_FOOTER_SIZE`. Harmless now, goes away when the image manager is enabled in the first upload and swap.
- sysbuild files live in `app/sysbuild/`, not a top level `sysbuild/`. Zephyr only picks them up from the app folder.

# Upload and swap

## Result

`scripts/ota_update.py` takes the board from v1.0.0 to a confirmed v1.1.0 with no manual step.

```
before: slot0 v1.0.0 active confirmed, slot1 v1.0.0
upload done in 8.35 s (5614 B/s)
board: I: Image index: 0, Swap type: test
board: OTA app v1.1.0, blink 200 ms, TEST boot, not confirmed yet
board: health check OK, image confirmed
after:  slot0 v1.1.0 active confirmed, slot1 v1.0.0
RESULT OK: running v1.1.0, upload 8.35 s, bootloader+swap 4.48 s, total 18.25 s
```

## Flow

1. Host uploads the signed image over SMP on USART1 (ST-LINK VCP). It lands in slot 1 on QSPI.
2. Host marks slot 1 for test, then sends an SMP reset.
3. MCUboot verifies the signature, swaps the slots, boots the new image once.
4. App runs for 5 s, then checks health: LED GPIO ready and slot 1 flash reachable.
5. On pass the app calls `boot_write_img_confirmed()`. Without that call the next reset reverts.
6. Host reads the console for the confirm line, then reads the slot state over SMP.

## Numbers so far (2 runs, not the measurement series)

| Item | Run 1 | Run 2 |
|---|---|---|
| Signed image | 46763 B | 46864 B |
| Upload | 9.97 s | 8.35 s |
| MCUboot + swap | 4.53 s | 4.48 s |
| Total, upload to confirmed | 19.90 s | 18.25 s |

Run 2 has `CONFIG_MCUMGR_GRP_OS_MCUMGR_PARAMS=y`, so the client reads the buffer size from the board.
The total includes the fixed 5 s health window.

App with SMP: 46612 B flash, 13888 B RAM (before the params option was added).

## Commands that worked

```sh
source ~/zephyrproject/.venv/bin/activate
scripts/build.sh 1.0.0 -p always
scripts/build.sh 1.1.0 -p always
(cd ~/zephyrproject && west flash -d "$OTA_KIT/build/v1.0.0" --runner openocd)
scripts/ota_update.py build/v1.1.0/app/zephyr/zephyr.signed.bin
```

## Notes

- Console and SMP share one UART. The app prints only at boot and at confirm, so frames stay clean.
- `scripts/build.sh` rewrites `app/VERSION` for the build and restores it after.
- No downgrade protection: uploading v1.0.0 over v1.1.0 is accepted. Listed as a known limit.

# Watchdog additions

Sizes with the watchdog, health thread and reset cause readout (from build output):

| Image | Flash | RAM |
|---|---|---|
| MCUboot | 40204 B of 64 K (61.35%) | 15552 B |
| App v1.0.0 | 47532 B | 15104 B |
| Signed app, v2.0.0 | 47683 B | |

# Fresh clone check

2026-10-07, on the development machine. A new clone of the repository in an empty directory, with the workspace, the SDK, the Espressif blobs and the Python packages already installed. So the list of prerequisites in the README was **not** tested on a clean machine.

| Step | Result |
|---|---|
| `imgtool keygen -k keys/ota_signing.pem -t ecdsa-p256` | ran |
| `scripts/build.sh 1.0.0`, `scripts/build.sh 1.1.0` (STM32) | built |
| `scripts/ota_doctor.py build/v1.1.0` | 16 PASS, 6 INFO, 1 WARN, 0 FAIL, 0 UNKNOWN |
| `python3 -m unittest discover -s tests/doctor`, `tests/check_paths.py` | OK |
| `west patch ... apply` for the Espressif HAL | `1 patches applied successfully` |
| `BOARD=esp32_devkitc/esp32/procpu VARIANT=wifi scripts/build.sh 1.0.0` and `1.1.0`, with the patch | built, the two `Cache_Flush` calls are in the image |
| `scripts/ota_doctor.py build/esp32-wifi-v1.1.0` | 11 PASS, 8 INFO, 1 WARN, 0 FAIL, 3 UNKNOWN |
| Taking the patch out with `git apply -R` | HAL tree unchanged afterwards |
| `samples/minimal` for `native_sim/native/64` | built and started |
| `west flash` and `scripts/ota_update.py` on the STM32 | **not run** in this check. Run from a fresh clone once before, with an earlier version of the tree |
| `west flash`, `scripts/wifi_provision.py`, `scripts/ota_update.py --udp` on the ESP32 | **not run** from a fresh clone. The same scripts were used for every Wi-Fi result |
| An ESP32 image built with the patch, on the board | Run later from the working repository, not from a fresh clone: failure suite 10 of 10 and 5 of 5 update runs. See [BOARD_ESP32.md](BOARD_ESP32.md), "Carrying the upstream fix". Most Wi-Fi results are from builds without the patch |

