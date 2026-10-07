# Second board: ESP32 WROOM-32

Tried on 2026-10-06. One dev board, one day. Every result below is from that board.

**Verdict: Wi-Fi passed its suite three times and 30 update runs, UART is partial, Bluetooth is not tested.** MCUboot, signed updates, rollback and the watchdog work.
More receive buffers made unanswered SMP requests over UART rare, not gone (the UART defect study and the re-test after a cable change).
Latest runs, 2026-10-07, new cable: soak 39 of 40 and later 40 of 40, suite 10 of 10 and then 9 of 10.
See "Re-test after a cable change" and "Port open and connect failures".

Status words: **working** (ran on the board), **partial** (ran, with a defect), **not working**, **not run**.

## How to build and update over Wi-Fi

This section is written in the style of Simplified Technical English. The results start at "Summary".

You need, in addition to the list in the README:

- The `xtensa-espressif_esp32_zephyr-elf` toolchain of the Zephyr SDK.
- The Espressif HAL in the workspace.
- An ESP32 dev board on USB. The examples use `/dev/ttyUSB0`.
- A 2.4 GHz WPA2 network. The host computer must be on the same network.

1. Get the radio files. They are binary files from Espressif, and the Wi-Fi driver does not build without them.

   ```sh
   cd ~/zephyrproject
   west blobs fetch hal_espressif
   ```

2. Apply the patch to the Espressif HAL. Set `KIT` to the folder of this repository.

   **WARNING: Do this step again after each `west update`. Without the patch, a build can make an image that stops before `main()`, and the build gives no warning.**

   ```sh
   KIT=/path/to/ota-kit
   west patch -l $KIT/zephyr/patches.yml -b $KIT/zephyr/patches -dm modules/hal/espressif apply
   ```

   The patch adds two lines that Zephyr issue #120719 proposes. "Carrying the upstream fix" below gives the reason.

   **WARNING: Do not use `west patch clean` for this module. It deletes the radio files.**

3. Build two versions of the example application.

   ```sh
   cd $KIT
   BOARD=esp32_devkitc/esp32/procpu VARIANT=wifi scripts/build.sh 1.0.0
   BOARD=esp32_devkitc/esp32/procpu VARIANT=wifi scripts/build.sh 1.1.0
   ```

4. Check the build.

   ```sh
   scripts/ota_doctor.py build/esp32-wifi-v1.1.0
   ```

5. Flash MCUboot and version 1.0.0.

   **WARNING: `--erase` erases the full flash. Use it for the first flash only. It also erases a stored network.**

   ```sh
   (cd ~/zephyrproject && west flash -d "$KIT/build/esp32-wifi-v1.0.0" --esp-device /dev/ttyUSB0 --erase)
   ```

6. Store the Wi-Fi network on the board. The script asks for the network name and the passphrase. It does not show them and does not save them on the host.

   ```sh
   scripts/wifi_provision.py
   ```

   The board resets and prints `WIFI: joined, IP ...`. Write down the address.

   The board keeps the name and the passphrase in its flash as plain text. A person with the USB cable can read them.

7. Send version 1.1.0. Replace `ADDRESS` with the address from step 6.

   ```sh
   scripts/ota_update.py build/esp32-wifi-v1.1.0/app/zephyr/zephyr.signed.bin --udp ADDRESS --port /dev/ttyUSB0
   ```

   The last line must be `RESULT OK: running v1.1.0`.

Which steps were run: steps 1 to 4 from a new clone on 2026-10-07, with no hardware. Steps 5 to 7 were run on the board during the tests, with builds that did not have the patch. An image with the patch started one time on the board. Not run: steps 5 to 7 from a new clone.

## Summary

| Item | Status | Evidence |
|---|---|---|
| Zephyr board found | working | `esp32_devkitc`, target `esp32_devkitc/esp32/procpu` |
| MCUboot with sysbuild | working | boots, log below |
| Build through the module and the `ota-kit` snippet | working | `BOARD=esp32_devkitc/esp32/procpu scripts/build.sh 1.0.0` |
| Signed update over UART | partial | unanswered upload requests: 3 of 40 uploads before the buffer fix, 1 in about 100 after |
| Failure suite over UART | partial | latest: 10 of 10, then 9 of 10. See "Re-test after a cable change" |
| Signed update over Bluetooth LE | working | 2 of 2 updates |
| Failure suite over Bluetooth LE | not run | BLE counts as not tested on this board until it runs |
| Wi-Fi, SMP over UDP | working | 30 of 30 update runs, failure suite 9 of 9 in two passes. See "Wi-Fi results" and "More Wi-Fi evidence" |
| Encrypted images (`ENC=1`) | not run | |
| 20 measured update runs | not run | |
| Near full slot image | not run | |
| Power loss tests | not run | |
| Size guard | not working | not available on this SoC, see "Changes to the kit" |

## Feasibility facts

Zephyr `133c2eb7d3cb`, MCUboot `7ad67106`, the same tree as the STM32 work.

| Question | Answer | Source |
|---|---|---|
| Board | `esp32_devkitc`, targets `esp32_devkitc/esp32/procpu` and `.../appcpu` | `boards/espressif/esp32_devkitc/` |
| Doc page | `boards/espressif/esp32_devkitc/doc/index.rst` and `boards/espressif/common/building-flashing.rst` | Zephyr tree |
| Chip | ESP32-D0WD, revision v1.0 | `esptool` output |
| Flash size | 4 MB | read from the chip with `esptool flash-id`, and MCUboot prints `SPI Flash Size : 4MB` |
| MCUboot with sysbuild | Yes. The board's `Kconfig.sysbuild` makes MCUboot the default bootloader | `boards/espressif/esp32_devkitc/Kconfig.sysbuild` |
| Erase block, write block | 4096 B, 4 B | board devicetree, and the doctor: "both slots erase in 4096 B" |
| Default swap mode | swap using move | `share/sysbuild/images/bootloader/Kconfig`: `default MCUBOOT_MODE_SWAP_USING_MOVE if SOC_FAMILY_ESPRESSIF_ESP32` |
| Other modes | A scratch partition exists, so swap using scratch fits the layout. MCUboot's own ESP32 configuration uses upgrade only. Neither was built here | partition file, `boot/zephyr/socs/esp32_procpu.conf` |
| Default signing | None. The board default is `BOOT_SIGNATURE_TYPE_NONE` | `Kconfig.sysbuild` |
| Signing used here | ECDSA P256, tinycrypt, the same key as the STM32 | `.config` of the MCUboot build |
| Image format | `esptool elf2image` makes `zephyr.bin`, `imgtool sign` adds the MCUboot header (0x20 bytes) and trailer to make `zephyr.signed.bin` | build log, `CONFIG_ROM_START_OFFSET=0x20` |

### Flash layout

From `partitions_0x1000_amp_4M.dtsi`, the file the board includes. Not changed by this project.

| Partition | Offset | Size |
|---|---|---|
| `boot_partition` (MCUboot) | 0x1000 | 60 K |
| `sys_partition` | 0x10000 | 64 K |
| `slot0_partition` | 0x20000 | 1344 K, 336 sectors |
| `slot1_partition` | 0x170000 | 1344 K, 336 sectors |
| slots for the second core and the low power core | after slot 1 | not used here |
| `storage_partition` | 0x3b0000 | 192 K |
| `scratch_partition` | 0x3e0000 | 124 K, not used by swap using move |

Both slots are on the one SPI flash and have the same size.
Swap using move keeps one sector free, so the largest image MCUboot can swap is 1363968 B (doctor, SIZE-01).

### Transports, from the docs

| Transport | Docs | Tried |
|---|---|---|
| UART | `uart` in the board's supported list. UART0 goes to the USB serial chip | yes |
| Bluetooth LE | The doc page says "integrated Wi-Fi & dual-mode Bluetooth". The devicetree sets `zephyr,bt-hci = &esp32_bt_hci`. Needs binary blobs: `west blobs fetch hal_espressif` | yes |
| Wi-Fi | `netif:wifi` in the board's supported list. Zephyr has `MCUMGR_TRANSPORT_UDP`. Needs the same blobs | no |

## What was installed for this

- Zephyr SDK toolchain `xtensa-espressif_esp32_zephyr-elf`, 191 MB on disk.
- Espressif radio blobs, `west blobs fetch hal_espressif`, 41 MB. Binary only, from Espressif.

## Changes to the kit

| Change | Why |
|---|---|
| Snippet `ota-kit` has an entry for `esp32_devkitc` | Sets `zephyr,uart-mcumgr = &uart0`. Without it the build fails, the board has no such chosen node |
| MCUboot console and log turned on for this board | MCUboot's ESP32 configuration turns the console off. The tests read the boot log |
| `CONFIG_BOOT_VALIDATE_SLOT0=y` set by the kit | MCUboot's ESP32 configuration turns it off. See "Slot 0 validation" |
| `OTA_KIT_SIZE_GUARD` now depends on `CPU_CORTEX_M` | It uses the linker symbol `_flash_used`, which the ESP32 linker script does not have. So there is **no size guard on the ESP32** |
| `OTA_KIT_BLE_DEVICE_ADDR_FROM_CHIP_ID` off by default on ESP32 | The ESP32 controller cannot be given an address. `bt_enable()` failed with -134. The chip has its own factory address |
| `UART_MCUMGR_RX_BUF_COUNT` is 8 by default on ESP32 | Unanswered SMP requests with the default of 2, see "UART defect" |
| Example app: `CONFIG_APP_ERASE_TRACE`, on by default on ESP32 only | Two console lines around a slot erase, so that case 10 can prove its timing |
| Watchdog of timer group 1 as `watchdog0`, started by MCUboot with 30 s | The default watchdog is reset away when the application starts. See "Early hang recovery" |
| Example app: the LED is optional | The board has no `led0` alias. The health check then only tests the slot 1 flash |
| `scripts/build.sh`, `tests/build_images.sh`, `tests/run_tests.py`: `BOARD` variable | Flash with `esptool`, reset through the USB serial adapter (EN pin), separate result files |

STM32 builds after these changes: app 47812 B and MCUboot 40512 B, the same sizes as before.
STM32 regression after these changes, 2026-10-06: the UART failure suite ran once on `disco_l475_iot1`, 10 of 10, no SMP timeout.
Every row matches the run before the changes (`tests/last_run.md`). The BLE suite and the power loss tests were not repeated.

## First boot

```
I (soc_init): MCUboot 2nd stage bootloader
I (flash_init): SPI Flash Size : 4MB
I: Starting bootloader
I: Primary image: magic=unset, swap_type=0x1, copy_done=0x3, image_ok=0x3
I: Secondary image: magic=unset, swap_type=0x1, copy_done=0x3, image_ok=0x3
I: Image index: 0, Swap type: none
I: Bootloader chainload address offset: 0x20000
I: Image version: v1.0.0
I: Jumping to the first image slot
*** Booting Zephyr OS build v4.4.0-13485-g133c2eb7d3cb ***
OTA app v1.0.0, blink 1000 ms, confirmed
watchdog armed, last reset by other cause
```

Sizes from the build: MCUboot 54096 B of 61440 B (88.0%). Signed app 160279 B over UART, 420376 B with Bluetooth.

**Erase the whole chip before the first flash.** The board came with MicroPython.
Flashed over it without an erase, MCUboot printed `Primary image: magic=bad` and the app printed `confirm write FAILED`.
Old bytes were left where the slot 0 trailer goes. After `west flash --erase` the log was the one above.

## First signed update over UART

`scripts/ota_update.py build/esp32-v1.1.0/app/zephyr/zephyr.signed.bin --port /dev/ttyUSB0`

```
board: I: Image index: 0, Swap type: test
board: I: Starting swap using move algorithm.
board: I: Image version: v1.1.0
board: OTA app v1.1.0, blink 200 ms, TEST boot, not confirmed yet
board: health check OK, image confirmed
after:  slot0 v1.1.0 active confirmed, slot1 v1.0.0
RESULT OK: running v1.1.0, upload 25.47 s, bootloader+swap 4.49 s, total 35.48 s
```

One run. Not a measurement series.

## Slot 0 validation

MCUboot's `boot/zephyr/socs/esp32_procpu.conf` sets `CONFIG_BOOT_VALIDATE_SLOT0=n`.
With that, MCUboot checks an update in slot 1 but not the image it boots from slot 0.

Test: the corrupted test image (4 flipped bytes, signature no longer matches) written straight to slot 0 with `esptool`.

| MCUboot build | Boot log |
|---|---|
| Option off, as the ESP32 default | `I: Image version: v2.0.4`, `I: Jumping to the first image slot`. It ran the corrupted image |
| Option on, set by the kit | `E: Image in the primary slot is not valid!`, `E: Unable to find bootable image` |

The option costs 96 B of MCUboot (54000 to 54096 B).
The doctor did not notice the option was off. It has no rule for it.

## Doctor

`scripts/ota_doctor.py build/esp32-v1.0.0`, first run: 11 PASS, 9 INFO, 1 WARN, 0 FAIL, 1 UNKNOWN.
After the UART defect study, with the new rule SIG-02: 12 PASS, 9 INFO, 0 WARN, 0 FAIL, 2 UNKNOWN.

Layout, sector, swap mode, signature, downgrade and health rules passed and match what the board did.

Rules it cannot judge on this SoC:

| Rule | Output | Why it cannot judge |
|---|---|---|
| SIZE-01 | First WARN, "the linker allows the application to grow to 4194176 B". Now UNKNOWN | That number is the whole 4 MB mapping of the ESP32 linker script, not a slot limit. The rule now says it cannot tell how far the application can grow. Nothing stops an oversized build here |
| WDT-02 | UNKNOWN, "No sourced limit for SoC series esp32" | The tool only has a sourced watchdog limit for the STM32 IWDG. The 10 s timeout did work on the board |
| WDT-01 | INFO, "MCUboot does not install a watchdog timeout" | True for the Zephyr option. Whether another ESP32 watchdog runs during MCUboot was not checked |
| FLASH-01 | INFO | The rule is only about an STM32 QSPI flash |
| SIG-02 | did not exist in the first run | Slot 0 validation off was found by hand. The rule was added in the UART defect study: WARN on the ESP32 default build, PASS with the kit |

## Failure suite over UART

`BOARD=esp32_devkitc/esp32/procpu tests/build_images.sh`, then `BOARD=esp32 tests/run_tests.py`.
Same 10 cases as on the STM32. Baseline before each case: whole chip erase, MCUboot and v1.0.0 written with `esptool`, reset.

Adapted for this board:

- Flash and reset: `esptool` and the EN pin through the USB serial adapter, instead of OpenOCD.
- Image without a signature: header 0x20, slot size 0x150000, alignment 4.
- Case 10: the reset comes 0.1 s after the erase request instead of 3 s. A slot 1 erase request returns in 0.7 s here.

All runs of the first ESP32 trial, in order. These are from before the buffer fix:

| Run | Result |
|---|---|
| Full run 1 | 10 of 10 passed. Case 10 was **not valid**: the reset came 3 s after a 0.7 s erase. MCUboot without slot 0 validation |
| Full run 2 | 9 passed. **Case 7 failed**: the upload that sets the case up timed out at 123501 of 160279 B. MCUboot without slot 0 validation |
| Case 10, 3 times | 3 passed. Raw rows: `docs/data/failure_runs_esp32_case10.csv` |
| Case 7, 5 times | 5 passed. Raw rows: `docs/data/failure_runs_esp32_case7.csv` |
| Full run 3 | **Aborted.** Cases 1, 2, 3 passed. The baseline before case 4 timed out: no answer to the slot 1 erase request in 120 s. Seven cases not run |
| Full run 4, final bootloader | 9 passed. **Case 7 failed** again: the same upload timed out, this time at 6703 B. Table: `tests/last_run_esp32.md`, logs: `tests/logs_esp32/` |

Full run 4, with slot 0 validation on:

| Case | Result | Note |
|---|---|---|
| 1 good update | PASS | swap, confirm, runs v2.0.0 |
| 2 failed health check | PASS | `Swap type: revert`, back on v1.0.0 |
| 3 wrong key | PASS | `E: Image in the secondary slot is not valid!` |
| 4 raw binary | PASS, different path | refused at upload, the same as on the STM32 |
| 4b no signature | PASS | rejected by MCUboot |
| 5 corrupted | PASS | rejected by MCUboot |
| 8 hang | PASS | chip reset itself after 10.1 s, `rst:0x7 (TG0WDT_SYS_RESET)`, `last reset by WATCHDOG`, revert |
| 10 reset during erase | PASS | v1.0.0 up 0.6 s after the reset. **No proof the reset landed inside the erase** |
| 7 downgrade | FAIL | the test did not get to its check, the first upload timed out. v1.0.0 kept running |
| 6 interrupted upload | PASS | killed at 80313 of 160279 B |

Downgrade prevention itself did work in run 1 and in the 5 single runs: `I: Image 0 in slot 1 erased due to downgrade prevention`.

### UART defect: unanswered SMP requests

**Setup, read from the build before any test** (`.config` and `zephyr.dts` of `build/esp32-v1.0.0/app`):

| Item | Value |
|---|---|
| Console | `uart0` (`zephyr,console`) |
| SMP | `uart0` (`zephyr,uart-mcumgr`, set by the kit's overlay). Console and SMP share the one UART that goes to the USB serial chip |
| Baud rate | 115200 (`current-speed`) |
| Flow control | none. `uart0` has no `hw-flow-control` property |
| UART driver mode | interrupt driven. `CONFIG_UART_ESP32_RX_FIFO_THRESH=0x16` |
| SMP line buffers | `CONFIG_UART_MCUMGR_RX_BUF_SIZE=128`, `CONFIG_UART_MCUMGR_RX_BUF_COUNT=2` |
| SMP frame buffers | `CONFIG_MCUMGR_TRANSPORT_NETBUF_SIZE=384`, `CONFIG_MCUMGR_TRANSPORT_UART_MTU=256` |
| Logging | off (`CONFIG_LOG` not set) |

The STM32 build has the same SMP values. An upload request from the host is 372 B of SMP payload, which is 5 lines on the UART.

**Reproduction.** `tests/uart_soak.py` repeats "erase slot 1, upload 160279 B" with no reset in between and records every request that fails.

Baseline, 40 uploads: **37 complete, 3 failed** (7.5%). Raw rows: `docs/data/esp32_uart_soak_baseline.csv`.

| Upload | Time | Request without an answer | Console after it |
|---|---|---|---|
| 4 | 21:31 | image upload, write, sequence 83, at offset 125979 | nothing |
| 6 | 21:32 | image upload, write, sequence 48, at offset 5991 | nothing |
| 35 | 21:44 | image upload, write, sequence 149, at offset 38387 | nothing |

The host waited 10 s each time. The board printed nothing in the 2 s after, and the next upload worked without a reset.
The console cannot be read during a request: it is the same port.

**Changes, one at a time.**

| Change | Uploads | Result |
|---|---|---|
| None (baseline) | 40 | 3 failed |
| 8 SMP line buffers instead of 2 (`CONFIG_UART_MCUMGR_RX_BUF_COUNT=8`) | 20 | **0 failed**. `docs/data/esp32_uart_soak_rxbuf8.csv` |
| Smaller chunks from the host: frames of at most 254 encoded bytes, 2 lines. Firmware unchanged, 2 buffers | 22 (16, then 6) | **0 failed**. `docs/data/esp32_uart_soak_frame254.csv`. Upload time 33.6 s instead of 26.0 s |
| Lower baud rate | not run | time box |
| Separate UART for SMP | blocked, needs owner | needs a second USB serial adapter wired to `uart1` or `uart2` |

In both soak runs with the small frames, the first request of the session got no answer. Each followed a session that had been cut off in the middle of a frame. That request is not counted above.

**What can be said.**

- Both changes that keep a request within the line buffers removed the failure over 20 uploads.
- Zephyr's `drivers/console/uart_mcumgr.c` drops a line when no buffer is free. It reports that only through a log message, `Insufficient buffers, fragment dropped`, and logging is off in this build.
- So the result fits this cause: a 5 line request sometimes overruns 2 line buffers on the ESP32.
- **Not shown directly.** The log message was not captured at a failure. With a 7.5% baseline rate, a clean run of 20 happens by chance about 1 time in 5, and two clean runs about 1 time in 25.
- Why the STM32, with the same values, never showed it is not known.

**Fix used here.** The kit sets `UART_MCUMGR_RX_BUF_COUNT` to 8 by default on ESP32. The STM32 keeps the default of 2 that it was tested with.
After the fix, on that day: 20 soak uploads and 16 suite cases, no unanswered SMP request.

**Correction.** The next day one upload request went unanswered with 8 buffers, in about 65 more uploads.
So the change made the failure rare. It did not remove it, and the cause above is **not confirmed**.

### Suite after the fix

Two passes in one run, `BOARD=esp32 tests/run_tests.py --repeat 2`. Rows: `docs/data/failure_runs_esp32.csv` and `tests/last_run_esp32.md`.

| Pass | Result |
|---|---|
| 1 | 9 of 10. **Case 1 failed**: the update worked and the slots read `slot0 v2.0.0 active confirmed`, but the console line `health check OK, image confirmed` arrived as 64 unreadable bytes, so the test did not see it |
| 2 | **Stopped.** Cases 1, 2, 3, 4, 4b, 5 passed. Then `esptool` failed while flashing the baseline for case 8. Its error text was not kept. Cases 8, 10, 7, 6 not run. The test script now logs the `esptool` output |

No SMP request went unanswered in either pass.

**Case 10 now proves its timing.** The ESP32 example app prints `slot erase start` and `slot erase done` (`CONFIG_APP_ERASE_TRACE`).
The test first lets one erase finish, then resets the chip as soon as the start line of a second erase arrives. Pass 1, host timestamps:

```
+0.000 s slot erase start
+0.646 s slot erase done          <- erase left alone: 646 ms
+0.000 s slot erase start
                                  <- reset sent 0.2 ms after the start line was read
+0.211 s rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)
+0.615 s OTA app v1.0.0, blink 1000 ms, confirmed
```

No done line between the start line and the reset. The reset pin is held for 200 ms, which is why the ROM line comes at 211 ms.
Limits: the times are taken on the host, after the USB serial adapter. The reset always lands at the very start of the erase, later points were not tried.

### Open: damaged bytes from the board to the host

Four single events, all on the way from the board to the laptop. None is explained. The buffer change does not address them.

| Event | When |
|---|---|
| An SMP answer with a wrong CRC | first request of a soak try, 3 s after flashing |
| One console line as 64 unreadable bytes | pass 1, case 1, the confirm line |
| One MCUboot line repeated about 469000 times | first BLE update, see below |
| `esptool` could not flash | pass 2, baseline of case 8. It worked again a minute later |

A different cable and a root port were tried in the re-test after a cable change, see "Re-test after a cable change".

## Re-test after a cable change

2026-10-07. Setup for every run below: a different USB cable, the one that had carried the ST-LINK data. ESP32 on a root port of the laptop (`lsusb -t`: bus 3, port 6, no hub in between). STM32 unplugged.
USB serial chip, from `/dev/serial/by-id`: Silicon Labs CP2102 USB to UART Bridge Controller. `esptool chip-id`: ESP32-D0WD, revision v1.0.
Firmware: the kit defaults, 8 SMP line buffers, slot 0 validation on.

### Soak, 40 uploads

39 complete, 1 failed. `docs/data/esp32_uart_soak_cable2.csv`.

| Upload | Time | Step | What happened |
|---|---|---|---|
| 1 | 09:44:06 | connect, the first request, 5 s after flashing | `SMPBadCRC: Packet CRC 0x7f6f != calculated CRC 0x2e98`. The port then delivered one 23 byte line, `BpYnVmX2NvdW50BP9/bw==`, 178 times in a row: the 4096 bytes that were read |
| 2 | 09:44:06 | connect | the first request got no answer in 2.5 s. The upload went on with default sizes and finished, 37.7 s instead of 26.5 s |
| 3 to 40 | | | complete, no failed request |

No upload request went unanswered in the soak.
The repeated line is the last line of the board's answer to that first request. The same error with the same CRC value happened once on the old cable (the UART defect study). **So this event does not depend on the cable.**

### Suite, two passes

`tests/last_run_esp32.md`, `docs/data/failure_runs_esp32.csv`.

| Case | Pass 1 | Pass 2 |
|---|---|---|
| 1 good update | PASS | PASS |
| 2 failed health check | PASS | PASS |
| 3 wrong key | PASS | PASS |
| 4 raw binary | PASS, different path | PASS, different path |
| 4b no signature | PASS | PASS |
| 5 corrupted | PASS | PASS |
| 8 hang | PASS, reset after 10.1 s | PASS, reset after 10.1 s |
| 10 reset during erase | PASS. Erase left alone 652 ms, reset 1.0 ms after the start line, no done line | **FAIL**. The upload that fills slot 1 for the test stopped: an image upload write request, sequence 170, got no answer in 20 s. The erase part did not run |
| 7 downgrade | PASS | PASS |
| 6 interrupted upload | PASS | PASS |

Pass 1: 10 of 10. Pass 2: 9 of 10. **Not two clean passes.**

### Case 10 sweep: reset 100, 300 and 500 ms into the erase

`BOARD=esp32 tests/run_tests.py erase-sweep 100 300 500`. An erase that is left alone took 652 ms in pass 1 (643 and 646 ms the day before).

| Delay asked | Reset sent after the start line | Done line before the reset | Reset lands | ROM line after | Then |
|---|---|---|---|---|---|
| 100 ms | 103.7 ms | no | inside the erase | +315 ms | v1.0.0 runs, `slot0 v1.0.0 active confirmed`, no MCUboot abort |
| 300 ms | 302.2 ms | no | inside the erase | +513 ms | same |
| 500 ms | 501.2 ms | no | inside the erase | +712 ms | same |

Rows: `docs/data/erase_sweep_esp32.csv`, logs: `tests/logs_esp32/erase-sweep-*.log`. One run per delay. Host timestamps, taken after the USB serial chip.
The reset pin is held low for 200 ms, so the ROM line comes about 210 ms after the reset.

### Link events in all runs of this session

Counted over the soak, both suite passes and the sweep, about 64 uploads. All with the cable setup above.

| Kind | Count | Time, step |
|---|---|---|
| Console line with unreadable bytes, away from a reset | 0 | |
| Console line with unreadable bytes at a reset edge | 27 | every hardware reset. The line that also carries the ROM banner. Seen in every earlier run too |
| CRC error in an SMP answer | 1 | 09:44:06, soak upload 1, connect. Followed by the repeated line |
| Request without an answer | 2 | 09:44:06, soak upload 2, connect, right after the repeated line. 10:13, suite pass 2, case 10, an upload request |
| `esptool` failure | 0 | 26 flashes |

Kernel log, `journalctl -k` from 09:43 to 10:20 (readable without extra rights, `dmesg` is not): 67 lines, **none** about USB, cp210x, ttyUSB or xhci. No disconnect or reset of the USB device was logged.

### What changed with the cable, and what did not

- Not seen again: an `esptool` failure, a garbled console line away from a reset. Each was seen once before, so their absence in one session is weak evidence.
- Seen again: the repeated last line with the CRC error. Seen again: an unanswered upload request.
- The repeated line came from after the UART wire in at least one case: the 469000 repeats of the first ESP32 trial were more bytes than a 115200 baud line carries. Whether the USB serial chip or the laptop repeats it is **not known**.
- Not tried: another dev board, another USB serial adapter, another computer. **Blocked, needs owner.**

## Port open and connect failures

2026-10-07, same setup as the re-test after a cable change: the second cable, ESP32 on a root port, STM32 unplugged. Firmware unchanged.

### How the port is opened

Read from the code, then checked on the board.

- `tests/uart_soak.py` and `scripts/ota_update.py` use `smpclient`, which uses pyserial. It creates the port object without a port name, then sets the name, calls `open()` and clears the input buffer.
- pyserial opens the device non blocking. On Linux **every such open raises DTR and RTS**. pyserial then writes its own state for DTR, then for RTS. Its default is both asserted.
- The port has `hupcl` set (`stty`), so closing it releases both lines.
- On this dev board RTS asserted with DTR released pulls the reset pin low.

| Open | Board reset, ROM banner seen right after |
|---|---|
| Default, both lines asserted | 0 of 10 |
| DTR and RTS set to released before the open | **10 of 10**. The open raises both, pyserial drops DTR first, and for a moment only RTS is asserted |
| The same, while another handle already holds the port open | 5 of 5 |
| Default open, then RTS released before DTR | 0 of 5 |

So the current scripts do not reset the board when they open the port.
"DTR and RTS held low before the port opens" cannot be done on Linux with this library: the lines can only be released after the open, and the order matters.

### Soak, two variants, 40 uploads each

| | A: current behavior | B: lines released before the open, wait for the app banner, then the first request |
|---|---|---|
| Uploads complete | 40 of 40 | 40 of 40 |
| Failures at connect | 0 | **40 of 40**: the first request, for the buffer sizes, got no answer in 2.5 s. The client went on with default sizes |
| Failures in the middle of an upload | 0 | 0 |
| App banner seen before the first request | not applicable, no reset | 40 of 40 |
| Mean time per upload | 26.1 s | 38.0 s |
| Runs of more than 5 identical console lines | 0 | 0 |
| Raw rows | `docs/data/esp32_uart_soak_open_a.csv` | `docs/data/esp32_uart_soak_open_b.csv` |

Why B fails at connect, shown by the table above it: the SMP client opens the port itself after the banner wait, and that open resets the board again. Its first request goes out while the board boots.
A 1 s wait after the banner did not change it (1 upload). In the suite, where the reset is a clean pulse with the port already open, the first request after a reset was answered in 25 of 25 baselines (the re-test after a cable change logs).

**B is worse than A and is not used.** Not built: a client that releases RTS and then DTR after the open. Time box.

### Detector for repeated console lines

- `tests/uart_soak.py`, `repeats()`: logs every run of more than 5 identical lines with the time, the upload number and the step.
- `scripts/ota_update.py`, `watch_boot()`: logs a console line that arrives more than 5 times in a row. This covers the failure suite.
- Limit: during an SMP request the port belongs to the client, so the soak sees the console only before the first request (variant B), for 0.3 s after each upload, and for 2 s after a failure.
- Result: 0 runs in 80 uploads. The repeated line of the re-test after a cable change did not come back in this session.

### What these numbers show, and what they do not

- The connect failure of the re-test after a cable change (1 in 40, the first request after flashing) was not caused by the scripts resetting the board at open. They do not.
- With the current behavior, soak uploads on this cable: 79 of 80 complete over the re-test after a cable change and the port open study. 1 failure at connect, 0 in the middle of an upload. In the suite of the re-test after a cable change, 1 upload request went unanswered.
- **Two runs of 40 cannot show that a rare failure is gone.** If the true rate were 1 in 100 uploads, a clean run of 40 would still happen about 2 times in 3.
- No cause is claimed for the repeated line or for the unanswered upload request.
- Kernel log, `journalctl -k`, 10:43 to 11:34: 21 USB lines, all about two other devices being plugged in at 10:57 and 10:59 (an audio device and a webcam), during soak A. None about cp210x or ttyUSB. Soak A had no failure.
- The failure suite was not run in this session. The board stays partial.

## Wi-Fi, SMP over UDP

2026-10-07. Same board, cable and port as the re-test after a cable change. Results of the runs on the network are in "Wi-Fi results" below.
The board has one open defect that also touches Wi-Fi builds, "early boot abort" below.

### Checked before building

| Question | Answer | Source |
|---|---|---|
| Wi-Fi station mode on `esp32_devkitc/esp32/procpu` | Supported. `netif:wifi` in the board's supported list, `&wifi { status = "okay"; }` in the board devicetree, driver `WIFI_ESP32` on by default | board yaml and dts, `drivers/wifi/esp32/Kconfig.esp32` |
| Binary blobs | Needed. `WIFI_ESP32` depends on `ZEPHYR_HAL_ESPRESSIF_MODULE_BLOBS`. `west blobs fetch hal_espressif`, done in the first ESP32 trial, 41 MB | driver Kconfig, `boards/espressif/common/system-requirements.rst` |
| Extra modules | None beyond `hal_espressif` and `mbedtls`, both already in the workspace. The driver selects `MBEDTLS` and `PSA_CRYPTO` | driver Kconfig |
| Does Zephyr's own Wi-Fi sample run | Yes. `samples/net/wifi/shell` built with sysbuild and MCUboot, flashed, reached its shell prompt | run on the board |
| SMP over UDP with MCUboot | Builds and boots. `MCUMGR_TRANSPORT_UDP`, port 1337, IPv4 | `subsys/mgmt/mcumgr/transport/Kconfig.udp`, run on the board |
| Wi-Fi together with the kit's BLE option | Not built, not run. Kconfig turns on `ESP32_SW_COEXIST_ENABLE` by default when both drivers are on. Its help text says software coexistence is "Recommended for heavy traffic scenarios". The board doc page has no warning about using both | `soc/espressif/common/Kconfig` |

Cost against the UART build of the same example app, from the build output:

| | UART | UART and Wi-Fi UDP |
|---|---|---|
| Signed image | 160855 B | 682071 B |
| Share of the largest image MCUboot can swap (1363968 B) | 11.8% | 50.0% |
| `dram0_0_seg` (data and bss) | 24432 B of 192 KB, 12.4% | 141128 B of 192 KB, 71.8% |
| `iram0_0_seg` | 36096 B | 59 KB |
| libc heap left, printed at boot | 168 kB | 54 kB |
| MCUboot | 54096 B | 54096 B, unchanged |

Both images fit their slots. The Wi-Fi image is 521 K larger.

### What was built

- Kit option `OTA_KIT_WIFI_UDP`, snippet `ota-kit-wifi`, `VARIANT=wifi` in `scripts/build.sh`. It adds SMP over UDP. **UART stays the console and stays an SMP transport.**
- `src/ota_kit_wifi.c`: joins a network stored on the board and prints `WIFI: joined, IP ..., ... ms after boot`.
- The network name and passphrase are **not in the build and not in this repository**. `scripts/wifi_provision.py` asks for them without echo, or reads two environment variables, and sends them to the board over SMP on the UART as the shell command `wifi cred add`. The board keeps them in its settings storage (Zephyr `wifi_credentials`), in plain text.
- A board that boots with a stored network refuses SMP shell commands (`MGMT_ERR_EACCESSDENIED`, checked with a dummy entry: return code 11). To store another network, erase the flash.
- Test baseline for Wi-Fi: everything below the storage partition is erased, not the whole chip, so the stored network survives. Checked with the dummy entry.

### Early boot abort that depends on the link layout

The first Wi-Fi build of the kit did not boot:

```
I (boot): libc heap size 54 kB.
I (spi_flash): detected chip: generic
I (spi_flash): flash io: dio
E (flash_init): Failed to init flash chip: 1
abort()
```

This is the application, before `main()`, in `esp_flash_config()` of the Espressif HAL. It happened on every boot of that image, also with the unchanged MCUboot of Zephyr's sample.

What was tried, each one a build flashed to the board:

| Build | Boots |
|---|---|
| Zephyr's `samples/net/wifi/shell`, no kit | yes |
| Kit, UART, plus only the Wi-Fi driver | yes |
| The same plus UDP, plus shell, plus settings and stored networks, plus SMP hooks | yes, each step |
| Kit Wi-Fi option with an empty `ota_kit_wifi.c` | yes |
| With the full `ota_kit_wifi.c`, two builds | **no**, both |
| Full file without the one call that registers the SMP hook | yes |
| Data segment padded to the same size as the failing build | yes |
| Full file plus one unused 4 byte data word | **yes** |

So the abort follows the link layout, not a feature. **The cause is not known.**

Later, 20 minutes on the cause. The failing image was built again (the first source of `ota_kit_wifi.c`, no extra word) and it failed again with the log above, byte for byte the same four lines.
A build of today's source without the extra word boots: the source has changed since, and with it the layout.

What the binaries show. `esp_flash_init_default_chip()` is in flash mapped code. It calls `esp_flash_init_main()`, which is in RAM, switches the flash cache off, talks to the flash chip and switches the cache on again. The table says where that call returns to:

| Image | Returns to | Bytes to the next 64 K flash page | Boots |
|---|---|---|---|
| Wi-Fi, first source, no extra word | 0x400dfff6 | **10** | **no** |
| Wi-Fi, today's source, no extra word | 0x400e0002 | 65534 | yes |
| Wi-Fi v1.0.0, v2.0.0, v2.0.1 | 0x400e0006 | 65530 | yes |
| Wi-Fi v1.1.0 | 0x400e0002 | 65534 | yes |
| Wi-Fi v2.0.5 | 0x400e000e | 65522 | yes |
| Zephyr's Wi-Fi shell sample | 0x400e0926 | 63194 | yes |
| UART v1.0.0 | 0x400d0f3e | 61634 | yes. 2 bytes before a 32 byte line, so a line boundary alone does no harm |
| Bluetooth v1.0.0 | 0x400d2d2e | 53970 | yes |

In the one failing image the code runs across a 64 K page boundary of the flash mapping 10 bytes after the cache was switched back on. In the nine booting images it does not.
**That is one failing sample. It is an observation, not a cause.** No experiment was made that moves only this address. The Wi-Fi images all sit within 30 bytes of that boundary, so the extra data word is a weak workaround: another change can move the code back.

**An existing upstream report, and its fix tested here.**

Zephyr issue #120719, "hal_espressif: ESP32 no-OS flash guard re-enables the cache without invalidating it", open, opened 2026-09-29, no comments when read on 2026-10-07: https://github.com/zephyrproject-rtos/zephyr/issues/120719

It says: before the kernel starts, flash operations switch the cache off and on again without invalidating it. A cache line whose fill was cut short can stay marked valid with partial content, and the next fetch from it runs garbage. The failure depends on the layout and shows right after `I (spi_flash): flash io: dio`. Its reporters saw a silent hang on a custom ESP32-D0WD board and had not run it on a DevKitC.
Here the symptom is a wrong return value and `abort()` instead of a hang, at the same place.

Its proposed fix is two lines in `components/spi_flash/spi_flash_os_func_noos.c` of `hal_espressif`: `Cache_Flush(0); Cache_Flush(1);` before the cache is switched on again. Tested on this board, with the change applied to the workspace for one build and removed again:

| Build of the failing layout (call at 0x400dfff3 in both) | Boot |
|---|---|
| Without the two lines | `E (flash_init): Failed to init flash chip: 1`, `abort()` |
| With the two lines | `OTA app v3.0.1, blink 1000 ms, confirmed`, joined the network |

One layout, one board, one boot each. **For this image the report's fix removes the abort.** The fix is not in the installed tree and not in this repository, so the defect is still there in every build made from it.
**Nothing here is claimed to be new.** The kit's extra data word stays as a workaround, and it is fragile: it moves the layout, it does not remove the fault.

Other results of the search for "Failed to init flash chip" (GitHub issue search, 2026-10-07, `zephyrproject-rtos/zephyr`, `zephyrproject-rtos/hal_espressif`, `espressif/esp-idf`): Zephyr #83743, an ESP32-S3 with octal PSRAM that freezes during boot, closed (https://github.com/zephyrproject-rtos/zephyr/issues/83743), and esp-idf #13380, restarts after a partition table change, closed (https://github.com/espressif/esp-idf/issues/13380). Both are other problems with the same message, only their descriptions were read. Whether esp-idf's own copy of that code has the same gap was not checked.

### An update that aborts before `main()`: no rollback without a reset

**Result: rollback failed. The board halted and stayed dead until an outside reset.**

Test: the failing image, signed as v3.0.0. Board on the good v1.0.0. Upload over Wi-Fi, mark for test, reset. Console timestamps are host side, seconds after the reset command returned.

```
+  0.252 s  rst:0xc (SW_CPU_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)
+  0.352 s  I: Image index: 0, Swap type: test
+  1.106 s  I: Starting swap using move algorithm.
+ 17.567 s  I: Image version: v3.0.0
+ 17.567 s  I: Jumping to the first image slot
+ 17.617 s  I (spi_flash): flash io: dio
+ 17.617 s  E (flash_init): Failed to init flash chip: 1
+ 17.617 s  abort()
```

| | Run 1 | Run 2 | Run 3, MCUboot built with a watchdog |
|---|---|---|---|
| Resets after the swap, by the board itself | 0 | 0 | 0 |
| Watched for | 120 s, then 15 s more with no console byte | 90 s | 110 s |
| Does `abort()` reset or halt | halt | halt | halt |
| Wi-Fi | no answer over UDP, ping 100% loss | no answer | no answer |
| After a reset pulse on the EN pin | `Swap type: revert`, v1.0.0 after 17.3 s, joined the network | the same, 17.3 s | the same, 17.3 s |

Facts behind it:

- Zephyr's `abort()` prints `abort()` and calls `k_panic()`. The default fatal error handler halts the CPU. Nothing resets the chip.
- The kit's watchdog is armed in an init function of the application. This abort comes earlier, in the SoC start code.
- MCUboot in the kit's ESP32 build has no watchdog: `CONFIG_WATCHDOG` is not set, `CONFIG_BOOT_WATCHDOG_FEED` is not set.
- Run 3: MCUboot built with `CONFIG_WATCHDOG=y` and a 30 s timeout (`CONFIG_BOOT_WATCHDOG_INSTALL_TIMEOUT_AT_BOOT=y`, 55952 B, it fits). **The board still stayed halted**, 92 s after the abort. Why that watchdog does not fire was not looked at. The standard bootloader was put back.
- MCUboot's part worked: the image was never confirmed, and on the next reset, of any kind, it was reverted.
- No full chip erase was needed. The stored network was kept.

**Since the early hang recovery work the kit's ESP32 setup recovers from this by itself, see "Early hang recovery" below.** The rest of this section describes the setup before that change.

What this means: on this board an update whose image dies before the kit's watchdog is armed leaves the device dead until someone resets or power cycles it. After that it comes back on the old version. Hazard HAZ-18 in [HAZARDS.md](HAZARDS.md).
The image used here is one that the build produced with no warning, from sources that boot with one more data word.

Workaround in the kit, not a fix: `CONFIG_OTA_KIT_WIFI_LAYOUT_PAD_WORDS`, default 1, adds that data word. Every Wi-Fi test image was booted once before the tests: all seven booted.
An image with this defect that arrives as an update would not confirm itself, and MCUboot would revert it. That path was not tested.

### Early hang recovery

2026-10-07. Question: why did a watchdog started by MCUboot not reset the halted board, and what does?

**Read from the source** (installed tree, file names given):

- Hardware. The board's `watchdog0` alias is `wdt0`, the main watchdog of timer group 0 (`esp32_common.dtsi`, `esp32_devkitc_procpu.dts`). `wdt1` is the one of timer group 1 and is disabled in the board file. The RTC watchdog has no Zephyr driver node here.
- Driver, `drivers/watchdog/wdt_esp32.c`. `wdt_setup()` configures two stages of the timeout each, the first raises an interrupt, the second resets, and starts the watchdog. So the driver does start it when MCUboot calls it. Its interrupt handler feeds the watchdog.
- MCUboot, `boot/zephyr/watchdog.c` and `main.c`. With `CONFIG_WATCHDOG` it installs `CONFIG_BOOT_WATCHDOG_TIMEOUT_MS` on the `watchdog0` alias, starts it and feeds it during a swap.
- The jump, `boot/zephyr/arch/esp32.c` and `hal_espressif/zephyr/port/boot/esp_image_loader.c`: nothing stops or changes the watchdog there.
- Reset time. In MCUboot's hardware init, `config_wdt()` in `hal_espressif/zephyr/common/soc_init.c` turns off the RTC watchdog and the flash boot protection of the RTC watchdog and of the timer group 0 watchdog. So after MCUboot's first lines no ROM watchdog is left running.
- The application's start code, `soc/espressif/esp32/soc.c`, calls `esp_timer_early_init()` before the flash init. In `hal_espressif/components/esp_timer/src/esp_timer_impl_lac.c` that function resets the registers of its timer group (`timg_ll_reset_register()`, a reset of the whole group through `DPORT_PERIP_RST_EN_REG`). The build uses `CONFIG_ESP_TIMER_IMPL_TG0_LAC=y`.

**Inferred, not read:** that this timer is in timer group 0 (from the option name), and that the group reset is what stops MCUboot's watchdog. The ROM code itself was not read. The experiments below fit the inference.

**One change at a time.** Failing v3.0.0 image in slot 0, MCUboot rebuilt for each row:

| MCUboot watchdog | Result | Boot log |
|---|---|---|
| None (the kit before this change) | not working, halted, the abort before main test | `abort()`, then nothing |
| Timer group 0, 30 s | not working, halted for 92 s, the abort before main test | `abort()`, then nothing |
| Timer group 0, shorter timeout, 5 s | **not working**, halted for the 39 s watched | `+0.905 s abort()`, then nothing |
| **Timer group 1, 30 s** | **working** | `+0.904 s abort()`, `+30.092 s rst:0x8 (TG1WDT_SYS_RESET)`, `+30.998 s abort()`, `+60.181 s rst:0x8 (TG1WDT_SYS_RESET)` |
| RTC watchdog armed in MCUboot before the jump | not run | needs new code in MCUboot. The row above met the requirement |

**Kit setup since this change**, for every ESP32 build of the kit:

- `watchdog0` is `wdt1` in MCUboot and in the application (`snippets/ota-kit/boards/esp32_devkitc.overlay`).
- MCUboot starts it with 30 s (`SB_CONFIG_OTA_KIT_MCUBOOT_WATCHDOG_TIMEOUT_MS=30000`, and the kit now also sets `CONFIG_WATCHDOG=y` for MCUboot).
- The application takes the same watchdog over with its 10 s timeout, as before.
- MCUboot grows to 56048 B, 91.2% of its partition. The doctor warns about that (SIZE-02).

**The failing image as an update over Wi-Fi, new setup, 2 runs:**

```
+  0.352 s  I: Image index: 0, Swap type: test
+ 17.523 s  I: Image version: v3.0.0
+ 17.573 s  E (flash_init): Failed to init flash chip: 1
+ 17.573 s  abort()
+ 46.787 s  rst:0x8 (TG1WDT_SYS_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)
+ 46.837 s  I: Image index: 0, Swap type: revert
+ 63.961 s  I: Image version: v1.0.0
+ 64.112 s  OTA app v1.0.0, blink 1000 ms, confirmed
+ 64.112 s  watchdog armed, last reset by WATCHDOG
+ 70.458 s  WIFI: joined, IP 192.168.x.x, 6428 ms after boot
```

| | Run 1 | Run 2 |
|---|---|---|
| Halted for | 29.2 s | 29.2 s |
| Reset by | the watchdog, `TG1WDT_SYS_RESET` | the same |
| Old version running, after the reset command | 64.1 s | 64.1 s |
| Back on the network | 70.5 s | 70.1 s |
| Slots afterwards | `slot0 v1.0.0 active confirmed, slot1 v3.0.0` | the same |

No reset from the host in either run.

**Healthy images and the application's own watchdog.** A healthy v1.0.0 under the new MCUboot ran 50 s with no reset, longer than MCUboot's 30 s. Then the Wi-Fi failure suite, third pass, with all images rebuilt: **10 of 10**, `tests/last_run_wifi_esp32.md`.

- Case 1, good update: confirmed. Cases 2 to 7 as before.
- Case 8, hang in `main()`: reset by the application's watchdog after 10.1 s, now `TG1WDT_SYS_RESET`, reverted.
- Case 9, new, `CONFIG_APP_HANG_EARLY`: an image that spins in a `PRE_KERNEL_1` init function, before the console and before `main()`. Reset by the watchdog 29.3 s after the jump, reverted, v1.0.0 runs, no reset from the test.

**Bounds and limits:**

- Worst case seen from the hang to the old version running: 30 s of watchdog plus 17 s of revert for a 682 K image.
- A gap is left. The application's watchdog driver stops the watchdog when it initialises, and the kit arms it again in a later init step. An image that hangs between those two is not covered. Not tested.
- Only the Wi-Fi builds were tested with the new setup. **The ESP32 UART and Bluetooth builds get the same change and were not rerun.**
- One UART console event in the suite log: after the last baseline flash with `esptool`, one line fragment arrived 378 times in a row, found by the detector. No Wi-Fi event. 22 duplicate answers dropped, 34 probes while joining, no unanswered request.

### Carrying the upstream fix

- Zephyr issue #120719 was open on 2026-10-07, no comments, no pull request linked in its timeline. A search of `zephyrproject-rtos/hal_espressif` for the function and file names found no pull request.
- The file `components/spi_flash/spi_flash_os_func_noos.c` on the `zephyr` branch of `hal_espressif`, fetched that day, has no `Cache_Flush` in `end()`. **The fix is not merged there.**
- The workspace has `hal_espressif` at `5e3b702250`, the revision Zephyr `133c2eb7d3cb` pins. The kit's `west.yml` imports Zephyr with an allow list of `mcuboot` and `zcbor`, so it does not pull the Espressif HAL at all. It could name `hal_espressif` with its own revision, but **there is no revision with the fix to pin**.
- What the kit carries instead, **not applied by any build**: `zephyr/patches.yml` and `zephyr/patches/hal_espressif/esp32-noos-flash-guard-cache-flush.patch`, for Zephyr's own `west patch` command. The command line is in the yml file. Applied once here: `1 patches applied successfully`, the two lines were in the HAL file.
- Cost: one command after every `west update`, a patched HAL in a shared workspace, and a patch to drop when the HAL gets the fix. The same two lines made the failing layout boot in the abort before main test. That test was not repeated through `west patch`.
- A warning from doing it: `west patch clean` also deleted the radio blobs of the HAL, they are untracked files. They were fetched again. The yml file says how to take the patch out without that command.
- A patch step inside the build was not built. The function is `static` in the HAL file, so it cannot be replaced at link time, and swapping a source file of the HAL's own library from a module is not simple.
- The extra data word (`CONFIG_OTA_KIT_WIFI_LAYOUT_PAD_WORDS`) stays, and stays **fragile**: it moves the layout, it does not remove the fault. With the watchdog setup above, an image that still hits the fault as an update is now reverted without help.

### Wi-Fi results

2026-10-07. Network: 2.4 GHz, WPA2. The laptop was on the same network. Its name and passphrase are not recorded anywhere in this repository.

**Join.** The board printed `WIFI: joined, IP 192.168.x.x, ... ms after boot` (DHCP, the same address every time).

| When | Join time after boot |
|---|---|
| First two joins, right after the network was stored | 5556 ms, 3998 ms |
| 10 baselines of the first measurement attempt | 5990 to 12171 ms |
| 10 baselines of the failure suite | 6039 to 12082 ms |

**First signed update over Wi-Fi**, v1.0.0 to v1.1.0, `scripts/ota_update.py IMAGE --udp 192.168.x.x --port /dev/ttyUSB0`:

- Attempt 1 stopped at 86791 of 682054 B: the host client raised `SMPBadSequence`, it had received the same answer twice.
- Attempt 2, with duplicate answers dropped on the host: upload 5.94 s (114837 B/s), MCUboot and swap 17 s, `health check OK, image confirmed`. The script's last read of the slots then timed out: it was sent before the board had joined the network again.

**10 update runs**, 682 K image, `tests/measure.py 10`:

| | Result |
|---|---|
| First attempt, `docs/data/update_runs_wifi_esp32_first_attempt.csv` | 2 of 10 by the script. All 10 images were confirmed on the console. The other 8 are the same timed out last read as above: **a mistake in the host script, not a failed update** |
| After the host fix, `docs/data/update_runs_wifi_esp32.csv` | **10 of 10** |
| Upload | 7.13 to 9.39 s, median 7.86 s |
| MCUboot and swap | 17.13 to 17.17 s, median 17.14 s |
| Upload start to confirmed | 30.13 to 32.22 s, median 30.95 s. Includes the fixed 5 s health window |

For comparison on this board: UART took 25.5 s to upload 160 K, Bluetooth 139 s for 420 K.

**Host changes that the Wi-Fi transport needed**, both in `scripts/ota_update.py`:

1. Answers whose sequence number is not the one just sent are dropped and logged. UDP may deliver a datagram twice.
2. After opening a UDP session the script asks for the image state every 2 s until the board answers, for up to 40 s. After a reset the board needs 4 to 12 s to join.

**Failure suite over Wi-Fi**, one pass, `tests/last_run_wifi_esp32.md`, logs in `tests/logs_wifi_esp32/`:

| Case | Result | Note |
|---|---|---|
| 1 good update | PASS | |
| 2 failed health check | PASS | reverted to v1.0.0 |
| 3 wrong key | PASS | rejected by MCUboot |
| 4 raw binary | PASS, different path | refused at upload, as on UART. Not in the list asked for |
| 4b no signature | PASS | rejected by MCUboot |
| 5 corrupted | PASS | rejected by MCUboot |
| 6 interrupted upload | PASS | killed at 341287 of 682070 B |
| 7 downgrade | PASS | Not in the list asked for |
| 8 hang | PASS | chip reset itself after 10.1 s |
| 10 reset during erase | not run | the case sends a raw frame on the UART |

9 of 9 cases that were run, in this first pass. The second pass and 20 more runs are in "More Wi-Fi evidence" below. Wi-Fi with a weak signal and a second device on the network were not run.

**Shell commands over the network.** `wifi cred list` sent over UDP was refused, return code 11.

### More Wi-Fi evidence

2026-10-07, same setup, the network already stored on the board.

**Every test image booted once before the suite**, written straight to slot 0 with the stored network kept: v1.0.0, v1.1.0, v2.0.0, v2.0.1, v2.0.3, v2.0.4 and v2.0.5 printed their banner, no early boot abort.
v2.0.2 is the image signed with the wrong key: `E: Image in the primary slot is not valid!`, `E: Unable to find bootable image`, as intended.

**Failure suite, second pass**: 9 of 9, the same cases as the first pass, case by case in `tests/last_run_wifi_esp32.md`.

| Case | Pass 1 | Pass 2 |
|---|---|---|
| 1 good update | PASS | PASS |
| 2 failed health check | PASS | PASS |
| 3 wrong key | PASS | PASS |
| 4 raw binary | PASS, different path | PASS, different path |
| 4b no signature | PASS | PASS |
| 5 corrupted | PASS | PASS |
| 6 interrupted upload | PASS | PASS, killed at 341287 of 682070 B |
| 7 downgrade | PASS | PASS |
| 8 hang | PASS | PASS, reset after 10.1 s |

**Case 10 over Wi-Fi: reset during a slot 1 erase.** The erase request went over UDP. The `slot erase start` line is printed on the UART console, not on the network, so **the timestamps are from the UART console** and the reset is the EN pin through the USB serial adapter.
An erase left alone, 682 K image in slot 1: 1002 ms from the start line to the done line (one run, after the sweep).

| Delay asked | Reset sent after the start line | Done line before the reset | Reset lands | Then |
|---|---|---|---|---|
| 100 ms | 103.4 ms | no | inside the erase | v1.0.0 runs, `slot0 v1.0.0 active confirmed`, no MCUboot abort |
| 300 ms | 304.9 ms | no | inside the erase | same |
| 500 ms | 500.9 ms | no | inside the erase | same |

Rows: `docs/data/erase_sweep_wifi_esp32.csv`, logs: `tests/logs_wifi_esp32/erase-sweep-*.log`. One run per delay.

**30 update runs**, `docs/data/update_runs_wifi_esp32.csv`. Runs 1 to 10 are from the first Wi-Fi session, runs 11 to 30 are new.

| | New 20 | All 30 |
|---|---|---|
| Updated and confirmed | 20 of 20 | 30 of 30 |
| Upload, 682 K | 7.32 to 8.83 s, median 7.77 s | 7.13 to 9.39 s, median 7.82 s, standard deviation 0.50 s |
| MCUboot and swap | 17.10 to 17.16 s, median 17.13 s | 17.10 to 17.17 s, median 17.14 s |
| Upload start to confirmed | 30.19 to 32.32 s, median 31.04 s | 30.13 to 32.32 s, median 31.03 s, standard deviation 0.59 s |

**Both suite passes and all 30 runs are clean.** All of it is from one afternoon, one board, one access point, with the laptop close by.


Counted from the run logs. A Wi-Fi event is something seen on the UDP side, a UART event something seen on the serial port. The console is on the UART in both cases.

| Event | UART (the re-test after a cable change and the port open study, about 144 uploads) | Wi-Fi UDP (the first Wi-Fi session and the second Wi-Fi session: about 60 full uploads) |
|---|---|---|
| Request without an answer, board up and reachable | 1 upload request | 0 |
| Request without an answer, sent too early | 2 connects, see below | First attempt: 9, the script did not wait for the join. Since the fix: 83 (6 and 13 in the run series, 26 and 30 in the suite passes, 8 in the sweep), each one a 2 s probe while the board was joining, by design |
| Duplicate or late answer | not possible to see, the serial client reads one frame | 148 in all: 2 in the first update, 23 and 24 in the two series of 10, 48 in the series of 20, 22 and 21 in the suite passes, 8 in the sweep. About 2.5 per 682 K upload. All dropped by the host |
| CRC error in an answer | 1 in the re-test after a cable change, 1 in the UART defect study, 1 when the network was first stored, 3 of 3 when reproduced | 0 |
| Same console line more than 5 times in a row | 1 in the first ESP32 trial, 1 in the re-test after a cable change, 0 since the detector exists | not a Wi-Fi event. 0 on the console during the Wi-Fi runs |
| `esptool` failure | 1 in the UART defect study | not a Wi-Fi event. 0 in 38 baseline flashes during the Wi-Fi runs |

**The UART CRC error now has a trigger.** Reproduced on 2026-10-07: flash with `esptool`, wait 5 s, send one SMP request. 3 of 3 times that first request failed with `SMPBadCRC` and the second one worked. With a reset pulse from the host between the flash and the request, the first request worked (1 of 1).
Every earlier CRC error was also the first request after an `esptool` flash. What `esptool` leaves behind on the port was not looked at. `scripts/wifi_provision.py` now tries its connect up to 3 times.

## Bluetooth LE

`VARIANT=ble BOARD=esp32_devkitc/esp32/procpu scripts/build.sh 1.0.0`, pairing with `bluetoothctl` as in the STM32 tests.

| Step | Result |
|---|---|
| First build | flashed, `BLE: bt_enable -134`. Cause: the fixed address option, see "Changes to the kit" |
| After the fix | `BLE: bt_enable 0`, the laptop found and paired with `ota-kit` |
| Update 1, v1.0.0 to v1.1.0 | OK. 420376 B in 139.25 s (3019 B/s), total 157.60 s |
| Update 2, after a fresh flash and pairing | OK. 139.25 s, total 157.42 s |

The host reconnected after the swap both times, so the bond and the address survived the reset.
SMP needs an encrypted link here too (`CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_ENCRYPT=y`). That an unpaired central is refused was **not run** on this board.

Seen once, not explained: during update 1 the host log shows one MCUboot line (`I: Starting swap using move algorithm.`) repeated about 469000 times in 10 s.
That is more bytes than a 115200 baud line can carry, so it is unlikely to be what the chip sent. The update finished correctly. Update 2 did not show it.

## Not covered on this board

- No secure boot and no flash encryption. The ROM does not verify MCUboot, and the USB port can rewrite or read the whole flash.
- No size guard.
- The BLE address is the chip's factory address.
- Timing was not measured in a series. The numbers above are single runs.
- Static analysis was not extended to this build. The erase trace code in the example app has 6 cppcheck MISRA findings that were not reviewed.
