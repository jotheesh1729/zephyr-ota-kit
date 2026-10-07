# Results

All output below is from the real board (B-L475E-IOT01A), captured on 2026-10-05.
The sections are in the order the work was done, so later sections correct or extend earlier ones.

# Failure handling

## How it was run

```sh
source ~/zephyrproject/.venv/bin/activate
tests/build_images.sh     # baseline v1.0.0 plus the test images
tests/run_tests.py        # all cases, about 6 minutes
```

- Raw table from the last run: `tests/last_run.md`
- Full console log per case: `tests/logs/<case>.log`
- Cases 1 to 6 ran twice on the firmware without a watchdog, then once more on the final firmware with the watchdog. Every run gave the same result for every case.
- Case 8 (watchdog) ran twice: once with the first feeder design, once on the final firmware. Both passed.
- The table shows the last run, on the final firmware.

Baseline before every case, scripted in `baseline()`:

1. Mass erase the internal flash over SWD.
2. Flash MCUboot and signed v1.0.0.
3. Erase slot 1 on the QSPI flash over SMP.
4. Assert the slot state is exactly `slot0 v1.0.0 active confirmed`.

## Test images

| Image | How it is made | `imgtool verify` with our public key |
|---|---|---|
| v2.0.0-good | `scripts/build.sh 2.0.0` | Image was correctly validated |
| v2.0.1-nohealth | `scripts/build.sh 2.0.1 -DCONFIG_APP_HEALTH_FORCE_FAIL=y` | Image was correctly validated |
| v2.0.2-badkey | `KEY=keys/wrong_key.pem scripts/build.sh 2.0.2` | No signature found for the given key |
| v2.0.3-unsigned | `zephyr.bin` from `scripts/build.sh 2.0.3`, raw | Invalid image magic |
| v2.0.3-nosig (extra) | same `zephyr.bin`, `imgtool sign` with no key: header and SHA256 only | No signature found for the given key |
| v2.0.4-corrupt | `scripts/build.sh 2.0.4`, then 4 bytes flipped at offset 0x2000 (header ends at 0x400) | Image has an invalid hash |
| v2.0.5-hang | `scripts/build.sh 2.0.5 -DCONFIG_APP_HANG=y`: main spins forever right after boot | Image was correctly validated |

## Result table

| # | Case | Expected | Actual | Result | Boot log proof |
|---|---|---|---|---|---|
| 1 | good | Swap, confirm, runs v2.0.0 | Swapped, ran v2.0.0 in test mode, confirmed after the health check. Slots: `slot0 v2.0.0 active confirmed, slot1 v1.0.0` | PASS | `I: Image index: 0, Swap type: test`<br>`I: Image version: v2.0.0`<br>`health check OK, image confirmed` |
| 2 | nohealth | Swap, no confirm, reset, rollback to v1.0.0 | Ran v2.0.1 unconfirmed (`slot0 v2.0.1 active, slot1 v1.0.0 confirmed`). After one reset MCUboot reverted. Slots: `slot0 v1.0.0 active confirmed, slot1 v2.0.1` | PASS | `health check FAILED, not confirming`<br>`I: Image index: 0, Swap type: revert`<br>`I: Image version: v1.0.0` |
| 3 | badkey | Upload ok, test, reset, MCUboot rejects, v1.0.0 runs | As expected. MCUboot also erased slot 1. Slots: `slot0 v1.0.0 active confirmed` | PASS | `I: Image index: 0, Swap type: test`<br>`E: Image in the secondary slot is not valid!`<br>`I: Image version: v1.0.0` |
| 4 | unsigned (raw) | Same as 3 | **Different path.** The running app refused the first upload chunk with `IMG_MGMT_ERR.INVALID_IMAGE_HEADER_MAGIC` (rc 23). Nothing was staged, MCUboot never saw it. v1.0.0 kept running. | PASS, different path | `I: Image index: 0, Swap type: none`<br>`I: Image version: v1.0.0` |
| 4b | nosig (extra) | Same as 3 | As expected. Upload and test accepted, MCUboot rejected it. Slots: `slot0 v1.0.0 active confirmed` | PASS | `I: Image index: 0, Swap type: test`<br>`E: Image in the secondary slot is not valid!`<br>`I: Image version: v1.0.0` |
| 5 | corrupt | Same as 3 | As expected. Upload and test accepted, MCUboot rejected it. Slots: `slot0 v1.0.0 active confirmed` | PASS | `I: Image index: 0, Swap type: test`<br>`E: Image in the secondary slot is not valid!`<br>`I: Image version: v1.0.0` |
| 6 | interrupted upload | Kill near 50%, reset, v1.0.0 runs | `ota_update.py` killed with SIGKILL at 24149/47683 B, board reset over SWD. v1.0.0 booted. Slots: `slot0 v1.0.0 active confirmed` | PASS | `I: Secondary image: magic=unset, ...`<br>`I: Image index: 0, Swap type: none`<br>`I: Image version: v1.0.0` |
| 8 | hang (watchdog) | Hung test image, IWDG resets the chip, MCUboot reverts, v1.0.0 runs, no reset from the script | v2.0.5 booted in test mode and hung. The chip reset itself 10.1 s later. MCUboot reverted. No reset was sent. Slots: `slot0 v1.0.0 active confirmed, slot1 v2.0.5` | PASS | `simulated hang: spinning, watchdog will not be fed`<br>`I: Image index: 0, Swap type: revert`<br>`I: Image version: v1.0.0`<br>`watchdog armed, last reset by WATCHDOG` |
| 7 | downgrade | Only if prevention is enabled | Not run. Downgrade prevention is not enabled, so v1.0.0 over v1.1.0 is accepted. | SKIPPED | none |

Rollback success across the failure cases (2 to 6, 4b and 8): 7 of 7 on the final firmware.
Earlier runs without the watchdog: 6 of 6, twice.

## Where the result differs from the expectation

**Case 4, raw unsigned binary.** The expectation was that the upload works and MCUboot rejects the image at boot.

What happened: the upload was refused on the first chunk, and MCUboot never saw the image.

Why:

- A raw `zephyr.bin` has no MCUboot header. An MCUboot image starts with the magic word `0x96f3b83d`. The raw binary starts with 0x400 bytes of padding instead, where the header would go.
- Zephyr's image manager checks that magic on the first upload chunk, before writing anything to flash:
  `subsys/mgmt/mcumgr/grp/img_mgmt/src/zephyr_img_mgmt.c`, `if (hdr->ih_magic != IMAGE_MAGIC) return IMG_MGMT_ERR_INVALID_IMAGE_HEADER_MAGIC;`
- The host saw that error as `IMG_MGMT_ERR.INVALID_IMAGE_HEADER_MAGIC` (rc 23). Slot 1 stayed empty, so the next boot shows `Swap type: none`.

What it means:

- The outcome is safe, so the result is "PASS, different path".
- This check is a format check in the app, not a security check. An attacker only has to add a valid header to get past it.
- The security check is MCUboot's signature verification, and case 4 does not reach it.
- Case 4b covers that gap: same binary, valid header and SHA256, no signature. It uploads fine and MCUboot rejects it.
- The test for case 4 was not changed to make it match.

## Watchdog

### Design

- The app arms the independent watchdog (IWDG) on the first line of `main()`, with a 10 s timeout.
- A health thread feeds it every 1 s. The same thread confirms a test image after the 5 s health window, and keeps feeding after that.
- A hung test image is never fed and never confirmed. The IWDG resets the chip, MCUboot sees an unconfirmed test image and reverts.
- Measured in case 8: 10.1 s from the hang to the MCUboot banner, then about 5 s for the revert swap.

### The MCUboot error `Watchdog install timeout failed: -22`

- Cause: MCUboot asks for a 300000 ms timeout. The STM32L4 IWDG tops out near 32.8 s (prescaler 256, 12 bit reload, 32 kHz LSI), so the driver returns `-EINVAL` (-22).
- Effect before the fix: MCUboot never started the watchdog.
- Fix: `CONFIG_BOOT_WATCHDOG_TIMEOUT_MS=30000` in `app/sysbuild/mcuboot.conf`. The error is gone (0 occurrences in the last full run).
- Option bytes: `FLASH_OPTR = 0xFFEFF8AA`, so `IWDG_SW = 1`. The watchdog is software started. Nothing starts it before MCUboot does.

### Does the IWDG run during the swap?

Yes, since the fix above. MCUboot starts it at 30 s and feeds it inside its copy and erase loops (`MCUBOOT_WATCHDOG_FEED`).
The app then takes it over with 10 s.

| Item | Value |
|---|---|
| MCUboot watchdog timeout | 30 s |
| Swap time, 47 K image | about 4.5 s (4.48 s and 4.53 s in the first upload and swap) |
| Revert swap in case 8 | about 5 s (1 s log resolution) |
| App watchdog timeout | 10 s |

For a 47 K image the swap is far below the timeout.
For an 840 K image the swap took 56 s, longer than the 30 s timeout, and the board did not reset. See the first measurement series. So the feeding during the swap works.

### Two problems found while adding it

**1. The watchdog fired during a slot 1 erase.**
The first design fed the watchdog from the lowest priority thread.
A whole slot erase runs in the SMP thread and busy polls the QSPI flash for about 15 s.
That starved the feeder, and the chip reset 9.4 s into the erase.
Fix: the health thread now runs one priority step above the SMP thread and below main.
After the fix the same erase finishes in 14.9 s with no reset.
The test was not changed. The firmware was.

**2. A reset during a QSPI erase stalls the boot for 30 s.**
Captured during problem 1:

```
 9.3 s  *** Using Zephyr OS build v4.4.0-13485-g133c2eb7d3cb ***
 9.4 s  I: Starting bootloader
 9.4 s  abort()
39.4 s  *** Using Zephyr OS build v4.4.0-13485-g133c2eb7d3cb ***
39.5 s  I: Starting bootloader
39.5 s  I: Image index: 0, Swap type: none
39.8 s  I: Image version: v1.0.0
```

The MCU reset does not reset the external flash chip, which is still busy erasing.
MCUboot cannot use it and calls `abort()`.
30 s later MCUboot's own watchdog resets the chip, the flash is idle by then, and the board boots normally.
Without the MCUboot timeout fix this would have been a permanent hang until a manual reset.
Fixed in the QSPI reset fix with a flash reset command at driver init. Boot after such a reset went from 30.6 s to 0.6 s.

### Evaluated: `CONFIG_IMG_ERASE_PROGRESSIVELY=y`

Question: does it remove the 15 s slot erase, so the feeder can go back to the lowest priority?

Experiment build: progressive erase on, health thread at `K_LOWEST_APPLICATION_THREAD_PRIO`.

| Test | Result |
|---|---|
| Upload onto a used slot 1 | OK. First chunk answered in 0.15 s, total 8.82 s |
| Upload again onto slot 1 holding v2.0.0 | OK. First chunk 0.15 s, total 8.53 s |
| SMP erase command on slot 1 holding v2.0.0 | **Watchdog reset at 9.8 s**, MCUboot `abort()`, recovered at 39.9 s |

Answer: only partly.

- It removes the up front erase from the upload path.
- It does not change the SMP erase command. That command always erases the whole slot in one driver call (`img_mgmt_erase_slot()` calls `flash_area_flatten()` on the full area).
- So the lowest priority feeder still fails the erase case. The feeder stays one step above the SMP thread.
- Progressive erase was not adopted for the measurements below. For this 47 K image the upload erase is small either way.

Proposal, not implemented: Zephyr `task_wdt` with one channel per thread.

- Channel for main, fed from the blink loop. Timeout a few seconds.
- Channel for the health thread. Timeout a few seconds.
- No channel for the SMP thread, or one with a timeout above the worst case erase.
- `task_wdt` feeds the IWDG from a kernel timer, not from a thread, so a busy thread cannot starve it. The IWDG stays as the fallback for a locked up kernel.
- This removes the priority trick and catches a hang in any thread that has a channel.

### Checked: can the QSPI driver recover a busy flash at init?

Driver: `drivers/flash/flash_stm32_qspi.c`, binding `st,stm32-qspi-nor`. Findings only, nothing patched.

| Mechanism | In the driver? | Usable on this board? |
|---|---|---|
| Reset command 0x66 then 0x99 at init | Yes. Devicetree property `reset-cmd`, with `reset-cmd-wait` in microseconds (default 10). Sent in both QPI and SPI mode. | Yes, by overlay. Not enabled in the board file. |
| Reset pin pulse at init | Yes. `reset-gpios`, `reset-gpios-duration`. | Not set in the board file. Needs a schematic check for a free reset line. |
| Wait for WIP to clear before the first command | No. Init only waits on WIP after it writes the quad enable bit. | Would need a driver change. |

Likely fix for problem 2: add `reset-cmd` and a long enough `reset-cmd-wait` to the `mx25r6435f` node, in the shared overlay so both MCUboot and the app get it.
Open point before patching: the reset recovery time of the MX25R6435F while an erase is running has to come from the datasheet. The 10 us default is probably too short.
Applied and tested in the QSPI reset fix.

### Test options are off in normal builds

`CONFIG_APP_HANG` and `CONFIG_APP_HEALTH_FORCE_FAIL` both default to off, and no committed `.conf` file sets them.
There is one configuration (`app/prj.conf`), used for every normal and release build.

| Build | `APP_HANG` | `APP_HEALTH_FORCE_FAIL` |
|---|---|---|
| v1.0.0 | not set | not set |
| v2.0.0 | not set | not set |
| v2.0.1-nohealth | not set | y |
| v2.0.5-hang | y | not set |

Added a guard: any build with one of them prints a compiler warning, "TEST IMAGE: built with a forced failure option. Never ship this build."

## What these tests do not prove

- **Hang coverage is partial.** The watchdog catches a hang in main or in any thread above the health thread. It does not catch a hang in the SMP thread or in lower priority threads.
- **Reset during a QSPI write.** Only a reset during an erase is tested (case 10). A reset during a page program is not.
- **Power loss during the swap.** Not tested. MCUboot is designed to resume a swap, but there is no measurement here.
- **MCUboot cannot tell cases 3, 4b and 5 apart in its log.** All three print the same line, `Image in the secondary slot is not valid!`. The reason (wrong key, no signature, bad hash) is known from how each image was built, and from `imgtool verify` in the table above.
- **Sample size.** Small. See "Measurement" for the 5 pass repeat.
- **The health check failure and the hang are forced** by build options. They are not real faults.
- **Worst case erase time.** The 15 s erase is one measurement on one chip. A slower erase does not trip the watchdog any more, but it does block SMP for that long.

# Measurement

All numbers are from the board, captured on 2026-10-05.
The update and big image numbers are from the final firmware (watchdog and QSPI reset fix included).
The 5 pass failure table is from the firmware just before the QSPI reset fix. The suite passed once more after it, see the QSPI reset fix.
Times are measured on the host with a monotonic clock.

```sh
tests/build_images.sh
tests/measure.py 20                # 20 updates plus one near full slot update
tests/run_tests.py --repeat 5      # failure suite, 5 times
```

Raw data:

- `docs/data/update_runs_after_qspi_fix.csv`: the 20 update runs in the table below
- `docs/data/big_image_run_after_qspi_fix.csv`: the near full slot run
- `docs/data/failure_runs.csv`: 40 failure suite rows (8 cases, 5 times)

## Update flow, 20 runs

The board alternates between v1.0.0 and v1.1.0, so every run is a real update and slot 1 always holds the previous image.

| Metric | Min | Mean | Median | Max | Std dev |
|---|---|---|---|---|---|
| Signed image size | 47850 B | 47850.5 B | 47850.5 B | 47851 B | |
| Upload time | 8.33 s | 8.37 s | 8.38 s | 8.45 s | 0.024 s |
| MCUboot + swap (MCUboot start to app jump) | 4.40 s | 4.41 s | 4.41 s | 4.43 s | 0.007 s |
| Total, upload start to confirmed | 18.25 s | 18.30 s | 18.30 s | 18.36 s | 0.024 s |

- **Success rate: 20 of 20.**
- The same 20 runs on the previous firmware (before the QSPI reset fix) also gave 20 of 20, with means of 8.39 s, 4.45 s and 18.32 s. That data is in `docs/data/update_runs_before_qspi_fix.csv` and `big_image_run_before_qspi_fix.csv`.
- Upload throughput: about 5.7 kB/s over the 115200 baud UART.
- The total contains a fixed 5 s health window. About 0.5 s is the rest: test request, reset, app start, state read.

## Near full slot update, 1 run

Image v1.3.0-big: 859911 B, padded with 812000 bytes. It fills 97.65% of what slot 0 can hold.

| Metric | Value |
|---|---|
| Signed image size | 859911 B (839.8 K) |
| Upload time | 136.28 s (6.3 kB/s) |
| MCUboot + swap | 55.93 s (about 2 s verify, about 54 s swap) |
| Total, upload start to confirmed | 197.71 s |
| Result | OK, confirmed |

Two things this run shows:

- **The swap was longer than MCUboot's 30 s watchdog timeout and the board did not reset.** So MCUboot does feed the IWDG during the swap. Before this run that was read from the code only.
- Swap time grows with image size: 4.41 s for 47 K, 56 s for 840 K. Swap using move only moves the sectors the image uses.

Measured twice, once per firmware revision: 55.98 s and 55.93 s. Only the second is in the CSV.

## Failure cases, 5 full passes

| Case | Runs | Result |
|---|---|---|
| 1 good | 5 | 5 PASS |
| 2 nohealth, rollback after reset | 5 | 5 PASS |
| 3 badkey | 5 | 5 PASS |
| 4 unsigned raw | 5 | 5 PASS, different path (refused at upload) |
| 4b nosig | 5 | 5 PASS |
| 5 corrupt | 5 | 5 PASS |
| 6 interrupted upload | 5 | 5 PASS |
| 8 hang, watchdog recovery | 5 | 5 PASS, chip reset 10.1 s after the hang in all 5 |

- **Rollback and rejection success rate: 35 of 35** across the seven failure cases (2, 3, 4, 4b, 5, 6, 8).
- Breakdown of the 35: 10 reverts of an image that had already booted (cases 2 and 8), 15 MCUboot rejections before boot (cases 3, 4b, 5), 5 upload refusals by the app (case 4), 5 interrupted uploads where nothing was staged (case 6).
- Case 7 (downgrade) was not run. Prevention is not enabled.

## Flash and RAM, from build output

| Image | Flash used | Region | RAM used | Region |
|---|---|---|---|---|
| MCUboot | 40368 B (61.60%) | 64 K boot partition | 15552 B (15.82%) | 96 K |
| App v1.0.0 | 47700 B (5.42%) | 868 K slot 0 | 15104 B (15.36%) | 96 K |
| App v1.3.0-big | 859760 B (97.65%) | 868 K slot 0 | 15104 B (15.36%) | 96 K |

The signed image is 150 B larger than the app flash figure: the linker figure already includes the 0x400 header space, and signing adds the hash and signature TLVs.

## Limits of these measurements

- One board, one host, one USB cable, one afternoon. No temperature or voltage variation.
- Host side timestamps. The swap figure includes MCUboot start up and signature verification.
- 20 runs give a mean, not a failure rate. 20 of 20 does not show that failures are rare.
- The big image was measured twice.
- No power cut was ever applied during an upload or a swap.

# QSPI reset fix, watchdog decision, power cut plan

## QSPI flash reset at driver init

Problem: an MCU reset does not reset the external flash. If it was erasing, the next boot cannot use it, MCUboot calls `abort()`, and the board waits 30 s for MCUboot's watchdog.

Datasheet: Macronix MX25R6435F, Rev. 1.6 (August 2022), Table 13 "Reset Timing (Other Operation)".

| Reset recovery time, tREADY2 | Value |
|---|---|
| During a 4 K sector erase | 12 ms |
| During a 32 K or 64 K block erase | 12 ms |
| During a chip erase | 12 ms |
| During a program | 80 us |
| During a status register write | 0.1 ms |

Fix, in `app/boards/disco_l475_iot1.overlay`, shared by MCUboot and the app:

```dts
&mx25r6435f {
	reset-cmd;
	reset-cmd-wait = <15000>;   /* 12 ms from the datasheet plus margin */
};
```

The driver then sends 0x66 and 0x99 at init and waits 15 ms. Cost: 15 ms per boot stage, and 164 B more flash in MCUboot.

Test, now case 10 in `tests/run_tests.py`: fill slot 1, start a whole slot erase, hardware reset 3 s into it, time until the app banner.

| | Before | After |
|---|---|---|
| Time from reset to app banner | 30.6 s | 0.6 s |
| MCUboot `abort()` | yes | no |
| Result | FAIL | PASS |

Before, from the console:

```
I: Starting bootloader
abort()
(30 s of silence, then MCUboot's watchdog resets the chip)
I: Starting bootloader
I: Image index: 0, Swap type: none
I: Image version: v1.0.0
```

After:

```
I: Starting bootloader
I: Image index: 0, Swap type: none
I: Image version: v1.0.0
OTA app v1.0.0, blink 1000 ms, confirmed
```

The "before" run was done once and the "after" run twice. Both "after" runs gave 0.6 s.

## Full suite on the final firmware

One pass, 9 cases, all as expected:

| Case | Result |
|---|---|
| 1 good | PASS |
| 2 nohealth | PASS |
| 3 badkey | PASS |
| 4 unsigned raw | PASS, different path |
| 4b nosig | PASS |
| 5 corrupt | PASS |
| 6 interrupted upload | PASS |
| 8 hang, watchdog | PASS, reset 10.1 s after the hang |
| 10 reset during erase | PASS, 0.6 s to boot |

Raw table: `tests/last_run.md`. Logs: `tests/logs/`.

## Progressive erase and task_wdt

- `CONFIG_IMG_ERASE_PROGRESSIVELY` is **not enabled**.
- The 15 s whole slot erase is **not gone**, and enabling the option would not remove it. See "Evaluated: `CONFIG_IMG_ERASE_PROGRESSIVELY=y`" above.
- So `task_wdt` with per thread channels stays documented future work. Case 9 (hang in the SMP thread) was not built.
- Current coverage is unchanged: the watchdog catches a hang in main or above. It does not catch a hang in the SMP thread or below.

## Power cut during swap: what is needed (not built)

Hardware:

- A USB hub with real per port power switching. Check the `uhubctl` compatibility list first, many hubs do not switch VBUS.
- Better: a second switched 5 V source for the target only, so the ST-LINK stays powered and the console is not lost.

Software:

- `uhubctl` (`sudo apt install uhubctl`), and a udev rule or sudo so a script can switch the port.

Things to solve:

- Cutting the ST-LINK port removes `/dev/ttyACM0`. It comes back a second or two after power returns, after MCUboot has already printed. So either the log of the resumed swap is lost, or the target needs its own switched supply.
- The board picks its 5 V source with a jumper (JP4). The positions and any back powering through the debug lines have to be checked in the board user manual before wiring.
- Bulk capacitors hold the rail up for some milliseconds, so the cut time is not exact.

Test design:

- Use the 840 K image. Its swap lasts about 54 s, so a random cut lands in the swap easily.
- Cut at a random offset into the swap. Repeat at least 50 times.
- After each power up: the board must run a valid image, old or new, and the slot state must be consistent.
- Expect MCUboot to resume the swap. This is the test that really stresses the experimental logical sector option.

# BLE as a tested transport

Full detail, including the MTU and security findings, is in `docs/TRANSPORTS.md`. Summary of the measured results:

```sh
VARIANT=ble tests/build_images.sh
# set transport = "ble" in tests/config.toml
tests/run_tests.py
tests/measure.py 20
```

## Failure suite over BLE, 1 pass

| Case | Result | Proof line |
|---|---|---|
| 1 good | PASS | `Swap type: test`, `health check OK, image confirmed` |
| 2 nohealth | PASS | `Swap type: revert` |
| 3 badkey | PASS | `E: Image in the secondary slot is not valid!` |
| 4 unsigned raw | PASS, different path | refused at upload, `IMG_MGMT_ERR.INVALID_IMAGE_HEADER_MAGIC` |
| 4b nosig | PASS | `E: Image in the secondary slot is not valid!` |
| 5 corrupt | PASS | `E: Image in the secondary slot is not valid!` |
| 6 interrupted upload | PASS | killed at 60059 of 119747 B, `Swap type: none` |
| 8 hang | PASS | reset 10.1 s after the hang, `Swap type: revert`, `last reset by WATCHDOG` |
| 10 reset during erase | not run over BLE | the test is UART only |

Every case gave the same result as on UART. Raw table: `tests/last_run_ble.md`. Logs: `tests/logs_ble/`.

## 20 update runs over BLE

Encrypted link, 119.7 K image. Raw data: `docs/data/update_runs_ble_first_series.csv`.

| Metric | Min | Mean | Median | Max | Std dev |
|---|---|---|---|---|---|
| Upload time | 32.49 s | 33.60 s | 33.16 s | 36.27 s | 1.241 s |
| MCUboot + swap (19 of 20 runs) | 7.46 s | 7.81 s | 7.72 s | 8.23 s | 0.226 s |
| Total, upload start to confirmed | 52.33 s | 53.67 s | 53.25 s | 56.75 s | 1.357 s |

Success rate: 20 of 20. Throughput: 3568 B/s mean, against about 5.7 kB/s on UART.

## Differences from UART

- The BLE image is 2.5 times larger (BLE stack, pairing, bond storage), so upload and swap times are not a like for like comparison. Throughput is.
- BLE is slower per byte (0.62 times the UART throughput) and less steady (std dev of the total 1.357 s against 0.024 s).
- BLE needs a pairing step once, and again after every full flash erase.
- 2 BLE connects needed a second attempt (1 in the suite, 1 in the 20 runs). No UART connect ever did.
- One BLE run has no swap time: the host missed the first MCUboot line after the reset.
- UART regression after the script changes: cases 1, 6 and 10 rerun on UART, all PASS.

## Known limits added by BLE

- **Security gap.** The link is encrypted, but pairing is "Just Works". It does not authenticate the central and does not stop a man in the middle during pairing.
- **First come, first served.** The board keeps one bond. Whoever pairs first holds it until the storage partition is erased. That a second central is refused was not tested.
- **No pairing window.** Before the first pairing, anyone in radio range can pair.
- **Address.** A fixed public address made from the chip ID, not from a registered address block.
- **Privacy off.** With `CONFIG_BT_PRIVACY=y` pairing failed in the one attempt made. Not investigated.
- **Throughput ceiling.** The link layer carries 27 byte packets. Data length extension on this controller is reported as unsupported, **not verified** against an ST document.
- **Coverage.** One pass of the failure suite. No range, interference, or phone tests. Case 10 and the near full slot image were not run over BLE.

# The kit as a Zephyr module

The update code moved out of the application into a Zephyr module (this repository), switched on by a snippet.
The STM32 application was rebuilt only through the module and the snippet, and the tests were run again.

## Is it the same firmware?

Compared against the build from before the module, same Zephyr tree:

| Check | Result |
|---|---|
| Application `.config`, old against new | identical, apart from the new `CONFIG_OTA_KIT*` lines |
| MCUboot `.config` | identical, apart from one module marker line |
| Application devicetree (`zephyr.dts`, comments removed) | 0 differing lines |
| MCUboot devicetree | 0 differing lines |
| Kconfig warnings in the 8 test image builds | none |

## Cost of the module

| Image | Before | Through the module | Difference |
|---|---|---|---|
| Application flash | 47700 B | 47780 B | +80 B |
| Application RAM | 15104 B | 15104 B | 0 |
| Signed image | 47850 B | 47931 B | +81 B |
| MCUboot flash | 40368 B | 40368 B | 0 |
| MCUboot RAM | 15552 B | 15552 B | 0 |
| BLE application flash | 119596 B | 117680 B | -1916 B |
| BLE application RAM | 34414 B | 34014 B | -400 B |

The BLE build got smaller because the transport is now a choice: the BLE build no longer contains SMP over UART.

## UART failure suite, 1 pass on the module build

| Case | Before | Module build |
|---|---|---|
| 1 good | PASS | PASS |
| 2 nohealth | PASS | PASS |
| 3 badkey | PASS | PASS |
| 4 unsigned raw | PASS, different path | PASS, different path |
| 4b nosig | PASS | PASS |
| 5 corrupt | PASS | PASS |
| 6 interrupted upload | PASS | PASS |
| 8 hang, watchdog | PASS, reset after 10.1 s | PASS, reset after 10.1 s |
| 10 reset during erase | PASS, 0.6 s to boot | PASS, 0.6 s to boot |

No difference. Raw table: `tests/last_run.md`.

## 20 update runs on the module build

These runs are in `docs/data/update_runs_module_build.csv` and `big_image_run_module_build.csv`. The data from after the QSPI reset fix is in `update_runs_after_qspi_fix.csv` and `big_image_run_after_qspi_fix.csv`. The files without a suffix always hold the latest runs.

| Metric (mean of 20) | Before (the QSPI reset fix) | Module build | Difference |
|---|---|---|---|
| Success | 20 of 20 | 20 of 20 | none |
| Signed image | 47850 B | 47931 B | +81 B |
| Upload | 8.37 s | 8.48 s | +0.11 s (+1.3%) |
| MCUboot + swap | 4.41 s | 4.40 s | -0.01 s |
| Total | 18.30 s | 18.39 s | +0.09 s |

Module build, full spread: upload 8.43 to 8.60 s, MCUboot + swap 4.38 to 4.42 s, total 18.32 to 18.49 s.

Near full slot image: 859990 B, upload 138.26 s (was 136.28 s, +1.5%), MCUboot + swap 55.87 s (was 55.93 s), total 199.63 s (was 197.71 s).

### The upload is about 0.1 s slower. Why?

Not fully explained.

- Not the image size: 81 more bytes are about 0.014 s at this throughput.
- Not the host script, which was reworked in the first BLE series. Checked: the old script (the version of `scripts/ota_update.py` from the QSPI reset fix, private repo history only) and the new one were run in turn against the same module firmware, 3 uploads each. Old: 8.62, 8.46, 8.51 s (mean 8.53). New: 8.46, 8.48, 8.45 s (mean 8.47).
- So today's uploads are about 0.1 s slower with either script. The Zephyr configuration is identical. What remains is the moved code (the kit now starts the watchdog from an init function and is built as a library) or the host on the day. That was not separated.
- The swap time, which does not involve the host link, did not change.

## BLE on the module build, smoke test only

All 7 BLE images rebuilt through the module with no Kconfig warnings. Two cases run over BLE:

| Case | Result |
|---|---|
| 1 good | PASS, upload 35.06 s (3361 B/s) |
| 8 hang, watchdog | PASS, reset after 10.1 s |

The full BLE suite and the 20 BLE runs were not repeated on the module build. The numbers in the first BLE series are from the firmware before the module.

One thing went wrong first: the pairing step failed once. The laptop still held a bond for the same address from the firmware of the first BLE series, cached under the old device name, and the test's "forget the board" step looks the board up by name. Removing that bond by hand fixed it. It is a one time effect of renaming the device from `ota-stm32` to `ota-kit`, but it shows that the cleanup should go by address.

## Second example

| Build | Result |
|---|---|
| `samples/minimal` on `native_sim` | builds and runs, prints its banner. No MCUboot, no update, watchdog off (no `watchdog0` alias), transport "set up by the application" |
| `samples/minimal` on `nrf52840dk/nrf52840`, sysbuild and `-S ota-kit` | compiles with no Kconfig warnings: application 44324 B flash, MCUboot 29532 B. Never flashed |

## Limits

- One board on hardware. The module is only compile tested elsewhere.
- The test scripts are still written for this board, see `docs/PORTING.md`.
- The UART transport cannot be guarded by a Kconfig dependency on interrupt support: that creates a dependency loop with the Bluetooth option. It is a note in the help text instead.

# Size guard, downgrade prevention, encrypted images

## Size guard

Problem, found by the doctor in the first doctor runs: the linker allows an application of up to 880490 B, MCUboot can swap at most 876544 B.

Formula, from MCUboot `design.md`, "Swap using move":

```
largest image = min((sectors in slot 0 - 1) x sector size, slot 1 size) - trailer
              = min((217 - 1) x 4096, 884736) - 8192 = 876544 B
```

The first term is from the document. The second, that the image and its trailer also have to fit slot 1, follows from the same text ("both the primary and secondary slots both have a trailer"). On this board both give the same number.

Why Zephyr does not catch it: MCUboot's sysbuild code sizes the application by slot 0. It takes one sector off only when both slots have the same size. Here slot 0 is one sector larger than slot 1, as the document recommends, and nothing is taken off.

The guard is a linker assert in the module (`linker/size_guard.ld`, `CONFIG_OTA_KIT_SIZE_GUARD`, on by default with swap using move).
It works the limit out from the slot sizes in the devicetree, the sector size, and `CONFIG_ROM_END_OFFSET`. Nothing is hard coded.
It keeps 160 B in reserve, because the size of the signature and key TLVs is not known at link time.

| Image | Before the guard | With the guard |
|---|---|---|
| 879091 B (2547 B over) | builds, uploads in 140 s, refused by MCUboot | **build fails** with the message below |
| 64 B over the guard's limit | not tried | build fails |
| 876527 B (17 B under MCUboot's limit) | not tried | builds, uploads, swaps in 56.97 s, confirms |

```
OTA kit size guard: this image is larger than MCUboot can swap.
  It would build, sign and upload, and MCUboot would then refuse it.
  Limit = min((sectors in slot 0 - 1) x sector size, slot 1 size) - trailer.
```

So the limit is now tested from both sides on the board: 876527 B works, 879091 B does not.
The doctor rule SIZE-01 uses the same formula and reports the guard when it is on.

Not done: the guard does nothing without sysbuild (no trailer size is known then), or when the sector size cannot be found. Swap modes other than move have no guard.

## Downgrade prevention

Enabled in MCUboot: `CONFIG_MCUBOOT_DOWNGRADE_PREVENTION=y`, set by the `ota-kit` snippet through `SB_CONFIG_OTA_KIT_DOWNGRADE_PREVENTION`.

What the documentation says, and what is true here:

- MCUboot Kconfig help: "any upgrade must have greater major version or greater minor version with equal major version".
- MCUboot `design.md` says the version based check "is only available when the overwrite-based image update strategy is used".
- The source of the MCUboot version used here (`loader.c`, `check_downgrade_prevention()`) also runs the check for swap using move, scratch and offset. The document is behind the code.
- The comparison in the source covers major, minor and revision.

Test case 7: update to v2.0.0, confirm, then offer v1.0.0 again.

| | Result |
|---|---|
| Upload of v1.0.0 | **accepted** by the SMP server |
| Mark for test, reset | accepted |
| MCUboot at boot | `I: Image 0 in slot 1 erased due to downgrade prevention` |
| Running afterwards | v2.0.0, confirmed. Slot 1 empty |
| Verdict | PASS |

So the rejection happens at boot, not at upload.
The SMP server only compares versions when the host sets the "upgrade" flag in the upload request, which is the host's choice and therefore no protection. `CONFIG_MCUBOOT_BOOTLOADER_NO_DOWNGRADE` in the application does not change that.
An attacker loses nothing by trying, the device loses one upload and one boot cycle.

Checked as well: a revert of an unconfirmed image still works with this on (cases 2 and 8 below). A revert goes back to an older version on purpose and is not blocked.

Not covered: someone with a debug probe can write any version. Whether an equal version is accepted was not tested. Cost: 144 B in MCUboot.

## Encrypted images

Supported with swap using move: MCUboot `encrypted_images.md` describes it for swap upgrades without excluding a mode, and Zephyr's sysbuild only excludes direct XIP and the firmware updater mode.

It is a separate build option and not the default:

```sh
imgtool keygen -k keys/ota_enc.pem -t ecdsa-p256        # once, gitignored
ENC=1 scripts/build.sh 1.0.0                            # output in build/enc-v1.0.0
scripts/ota_update.py build/enc-v1.1.0/app/zephyr/zephyr.signed.encrypted.bin
```

How it works (MCUboot `encrypted_images.md`): imgtool encrypts the image with a random AES-128 key and wraps that key for the device with ECIES-P256. MCUboot decrypts while swapping into slot 0, and encrypts the old image again while moving it to slot 1.

### One update over UART

```
image build/enc-v1.1.0/app/zephyr/zephyr.signed.encrypted.bin, 48059 B
upload done in 8.44 s (5696 B/s)
I: Image index: 0, Swap type: test
I: Image version: v1.1.0
OTA app v1.1.0, blink 200 ms, TEST boot, not confirmed yet
health check OK, image confirmed
RESULT OK: running v1.1.0, upload 8.44 s, bootloader+swap 6.11 s, total 20.05 s
```

### Is the file on the wire plain?

Compared `zephyr.signed.bin` and `zephyr.signed.encrypted.bin` of the same build:

| Check | Plain | Encrypted |
|---|---|---|
| Entropy of the payload, bits per byte | 6.982 | 7.995 |
| Strings `OTA app v`, `health check`, `Booting Zephyr` | all found | none found |
| Payload bytes equal to the plain image at the same offset | | 183 of 46756 (0.39%, chance is 0.39%) |
| Header flag | 0x0 | 0x4, encrypted with AES-128 |

The header, including the version, and the TLVs stay plain, as the MCUboot document says.
This compares the files. The bytes on the UART were not captured separately, the script sends the file as it is.

### Cost

| | Plain | Encrypted | Difference |
|---|---|---|---|
| MCUboot flash | 40512 B | 45808 B | +5296 B, now 69.9% of the 64 K partition |
| MCUboot RAM | 15552 B | 15936 B | +384 B |
| Application | 47780 B | 47780 B | none |
| Update file | 47931 B | 48060 B | +129 B, the wrapped key |
| MCUboot + swap, 47 K image | 4.39 s mean of 20 | 6.11 s, 1 run | about +1.7 s |

### Two more things tried on the board

| Test | Result |
|---|---|
| A plain signed image sent to the bootloader that has encryption enabled | **Accepted**, swapped and confirmed. Encryption is not enforced: it protects images that are encrypted, it does not refuse ones that are not |
| An encrypted image that hangs at boot | Watchdog reset, `Swap type: revert`, the old version runs. So the old image survived being encrypted into slot 1 and decrypted back |

### Key handling, and what it does not protect

- Two key pairs: the signing key as before, and an encryption key pair, `keys/ota_enc.pem`. Both private keys are files on the build host and are gitignored.
- **MCUboot holds the private encryption key in its own flash.** It needs it to unwrap the image key at every update.
- **On this board the internal flash is readable.** Readout protection is off (RDP level 0) and the debug port is open. Anyone with a probe can read MCUboot, take the private key, and decrypt every update ever made for these devices. They can also simply read the decrypted image out of slot 0.
- So on a readable device encryption protects exactly two things: the update file in transit and in storage, and the copy in slot 1 on the external flash, which can be read with a clip without touching the MCU.
- It protects nothing against someone who can read the internal flash. That needs readout protection, which this project does not set up.
- All devices built with the same key share it. One extracted key opens them all.
- `CONFIG_BOOT_SWAP_SAVE_ENCTLV=y` is set for these builds. Without it MCUboot writes the plain image key into the swap metadata, and here that metadata is partly on the external flash (MCUboot `encrypted_images.md`).
- The header and the version of an encrypted image are not hidden.

Not done: more than one encrypted run for timing, the failure suite on the encrypted build, AES-256, BLE with encryption.

## Tests on the final firmware

Final firmware: size guard and downgrade prevention on, encryption off.

UART failure suite, 1 pass:

| Case | The module build | The final firmware series |
|---|---|---|
| 1 good | PASS | PASS |
| 2 nohealth | PASS | PASS |
| 3 badkey | PASS | PASS |
| 4 unsigned raw | PASS, different path | PASS, different path |
| 4b nosig | PASS | PASS |
| 5 corrupt | PASS | PASS |
| 6 interrupted upload | PASS | PASS |
| 7 downgrade | not run, prevention was off | PASS, rejected at boot |
| 8 hang, watchdog | PASS, 10.1 s | PASS, 10.1 s |
| 10 reset during erase | PASS, 0.6 s | PASS, 0.6 s |

20 update runs:

| Metric (mean of 20) | The module build | The final firmware series | Difference |
|---|---|---|---|
| Success | 20 of 20 | 20 of 20 | none |
| Signed image | 47931 B | 47931 B | none |
| Upload | 8.48 s | 8.48 s | none |
| MCUboot + swap | 4.40 s | 4.39 s | -0.01 s |
| Total | 18.39 s | 18.38 s | -0.01 s |

Near full slot image: 859991 B, upload 138.32 s, MCUboot + swap 56.01 s, total 199.82 s (the module build: 138.26, 55.87, 199.63).

One change in how the 20 runs are made: with downgrade prevention each update needs a higher version, so the same two binaries are signed again under versions 1.11.0 to 1.30.0. The image content alternates as before. No measurable difference came from it.

Sizes: application 47780 B flash and 15104 B RAM, unchanged. MCUboot 40512 B, +144 B for downgrade prevention.

BLE: the BLE image was rebuilt on the final firmware and checked with the doctor. No BLE test was run in this series.

# BLE regression, quality and safety documents

## BLE regression on the final firmware

BLE images rebuilt with the size guard and downgrade prevention, then one pass of the failure suite and 5 update runs over BLE.

| Case | The first BLE series | The BLE regression |
|---|---|---|
| 1 good | PASS | PASS |
| 2 nohealth | PASS | PASS |
| 3 badkey | PASS | PASS |
| 4 unsigned raw | PASS, different path | PASS, different path |
| 4b nosig | PASS | PASS |
| 5 corrupt | PASS | PASS |
| 6 interrupted upload | PASS, killed at 60059 of 119747 B | PASS, killed at 58979 of 117831 B |
| 7 downgrade | not run, did not exist | PASS, `Image 0 in slot 1 erased due to downgrade prevention` |
| 8 hang, watchdog | PASS, 10.1 s | PASS, 10.1 s |
| 10 reset during erase | not run, UART only | **not rerun**, UART only |

Update runs over BLE. The data of the first BLE series is kept in `docs/data/update_runs_ble_first_series.csv`, the new runs are in `update_runs_ble.csv`.

| Metric (mean) | The first BLE series, 20 runs | The BLE regression, 5 runs | Difference |
|---|---|---|---|
| Success | 20 of 20 | 5 of 5 | none |
| Signed image | 119742 B | 117831 B | -1911 B, the BLE build no longer contains SMP over UART |
| Upload | 33.60 s | 36.03 s | +2.43 s (+7%) |
| Throughput | 3568 B/s | 3273 B/s | -8% |
| MCUboot + swap | 7.81 s | 7.48 s | -0.33 s, smaller image |
| Total | 53.67 s | 56.05 s | +2.38 s |

Differences, stated plainly:

- **Uploads were slower, and the cause is not known.** The image is smaller and the firmware's Bluetooth configuration is the same as far as the build shows. The BLE regression has 5 runs against 20, all five between 34.33 and 37.26 s, while the first BLE series ranged from 32.49 to 36.27 s. The radio environment was not controlled or recorded in either phase.
- 1 connect retry and 1 repeated scan in the suite, none in the 5 runs. The first BLE series had 2 connect retries in total.
- All 5 runs have a swap time. In the first BLE series one of 20 was missing.

Not rerun over BLE in this series: 20 runs (5 were asked for), case 10, the encrypted build, and the near full slot image.

## Static analysis and warnings

Summary. Method, tool versions and limits are in [QUALITY.md](QUALITY.md), the remaining findings in [DEVIATIONS.md](DEVIATIONS.md).

| | Before | After |
|---|---|---|
| cppcheck 2.13.0 with its MISRA addon, findings in this project's C files | 35 | 11, all documented |
| Strict compiler warnings located in this project's files | 1 | 0 |

This is not a MISRA compliance claim.

Two results along the way were wrong and were caught:

- The first cppcheck run said 0 findings, because cppcheck could not parse the code at all.
- The first strict warning build said 1 warning, because the extra flags never reached the compiler.

## Regression after the source fixes

The fixes touched `src/ota_kit.c`, `src/ota_kit_ble.c` and `app/src/main.c`, so the tests were run again on the changed code.

| Test | Result |
|---|---|
| UART failure suite, 1 pass, 10 cases | all as before. Hang reset after 10.1 s, reset during erase 0.6 s, downgrade rejected at boot |
| BLE, cases 1 and 8 only | both PASS, uploads 35.28 s and 36.49 s. One repeated scan |
| Full BLE suite, BLE runs, UART 20 runs, encrypted build | **not rerun** on the changed code |

So the full BLE regression above ran on the code just before the static analysis fixes, and the UART 20 run measurement is the one from the final firmware series.

Sizes after the fixes: application 47812 B (was 47780 B), BLE application 117780 B (was 117680 B), MCUboot 40512 B, RAM unchanged.

## Requirements, hazards, CI

- [REQUIREMENTS.md](REQUIREMENTS.md): 14 requirements tested on hardware, 5 checked on builds, 8 listed as not tested or not implemented.
- [HAZARDS.md](HAZARDS.md): 15 hazards with mitigation, evidence and residual risk. No certification, no ASIL.
- CI now has two jobs: host tests, and a native_sim build of the module followed by the static analysis. The steps were run in a fresh local workspace and pass. **The result on GitHub could not be checked from here.**
- The board build and all hardware tests are not in CI.

# Power loss

The supply of the board was cut with a relay at chosen moments of an update, restored after 2 s, and the result checked.
Setup, design, pass criteria and the full discussion are in [POWERLOSS.md](POWERLOSS.md). Raw data: `docs/data/powerloss_runs.csv` and `powerloss_latency.csv`.

Before the tests:

- With the relay open the MCU is off: no console output, OpenOCD cannot connect, and CN2 3V3 reads 300 mV on a multimeter (measured the day after the runs; a first reading was reported as "below 0.3 V"). The rail does not fall to 0 V. The source of the remaining 300 mV was not investigated.
- The ST-LINK reports about 3.22 V as target voltage in both relay states, 5 readings each. Unexplained.
- From the `OFF` command to the board going silent: 15.9 ms mean, 15.2 to 16.8 ms, 10 runs. Host side timing, with relay movement, contact bounce and the falling supply rail inside it.

| Phase | Cuts | Passed | New version | Old version | Failures |
|---|---|---|---|---|---|
| Upload, at about 25, 50 and 75 percent | 6 | 6 (100%) | 0 | 6 | none |
| Swap, 20 swept offsets, 12 random (seed 20261006), 5 repeats | 37 | 36 (97%) | 27 | 9 | 1 row not valid: a mistake in the test script, the board had reverted correctly |
| Revert swap after an unconfirmed image | 6 | 6 (100%) | 0 | 6 | none |
| Around the confirm | 6 | 6 (100%) | 4 | 2 | none |
| Slot 1 erase | 5 | 5 (100%) | 0 | 5 | none |
| Total | 60 | 59 | | | |

Pass means all five checks: boots without help, runs the old or the new version, ends confirmed, slot 0 equals the signed image byte for byte when read back over SWD, and boots a second time.

- **No cut needed manual recovery.** The board always came back by itself, in 0.6 to 4.9 s.
- A cut during the swap: MCUboot continued the swap after power came back. Time to the application fell from 4.70 s for a cut at 0.10 s to 0.72 s for a cut at 4.10 s.
- A cut after the swap but before the confirm: MCUboot reverted to the old version, as after any reset of an unconfirmed image. The update is lost, the device is fine.
- The confirm itself: cuts up to 4.97 s after the banner ended on the old version, cuts from 5.01 s on the new one.

Failures explained:

- **Row 38** is recorded as failed and is not counted as a pass. The test script read a banner that arrived just after `OFF` as the result, and checked slot 0 against the wrong version. The console log of that cut shows a normal revert to v1.0.0. The script was corrected and that offset was repeated three times, with two neighbours: all five passed.
- **A first attempt was stopped after 8 cuts**, because the script compared slot 0 of the baseline with a file that carries a different signature than the one flashed. Those rows are in `docs/data/powerloss_first_attempt.csv`. The run was started again from the beginning.

Limits: one board, one image size (47.9 K), a 2 s clean cut only. The cut is not sharp: relay jitter and bounce, and the capacitance of supply and board, smear it over milliseconds, so it is not an instant 0 V. No slow brown out, no glitches, no repeated cuts. The bench supply stayed in constant voltage mode according to the project owner, who watched it. The script does not monitor it. The ST-LINK USB stays connected while the external supply is cut and restored, which is not the power order the board's manual asks for (UM2153 Rev 5, section 7.5, as read by the project owner).

# An image that hangs before main(), STM32

2026-10-07, `disco_l475_iot1` on its ST-LINK USB port, JP4 on pins 1 and 2, UART transport. All test images rebuilt from the current sources.

The question came from the second board, where such an image first left the board dead ([BOARD_ESP32.md](BOARD_ESP32.md), HAZ-18 in [HAZARDS.md](HAZARDS.md)).
Test case 9: an image built with `CONFIG_APP_HANG_EARLY=y` spins in a `PRE_KERNEL_1` init function, before the console driver, before `main()` and before the kit arms its watchdog. It is uploaded, marked for test, and the board is reset once by the SMP reset command. After that the test sends no reset.

MCUboot on this board: `CONFIG_WATCHDOG=y`, `CONFIG_BOOT_WATCHDOG_INSTALL_TIMEOUT_AT_BOOT=y`, `CONFIG_BOOT_WATCHDOG_TIMEOUT_MS=30000`, driver `IWDG_STM32`. It starts the independent watchdog with 30 s and feeds it during a swap.

Boot log of the first run, host timestamps:

```
[18:05:01] reset sent
[18:05:01] I: Image index: 0, Swap type: test
[18:05:01] I: Starting swap using move algorithm.
[18:05:06] I: Image version: v2.0.6
[18:05:06] I: Jumping to the first image slot
                                              <- no line from the new image, 29.8 s
[18:05:35] I: Starting bootloader
[18:05:35] I: Image index: 0, Swap type: revert
[18:05:40] I: Image version: v1.0.0
[18:05:40] OTA app v1.0.0, blink 1000 ms, confirmed
[18:05:40] watchdog armed, last reset by WATCHDOG
```

| | Case 9, early hang, run 1 | Case 9, run 2 (in the full suite) | Case 8, hang in `main()` |
|---|---|---|---|
| Reset by MCUboot's watchdog, no outside help | yes | yes | not applicable, the application's 10 s watchdog was already armed |
| Jump to reset | 29.8 s | 29.8 s | 10.1 s after the hang line |
| Old version back | yes, about 5 s after the reset, `last reset by WATCHDOG` | yes | yes |
| Slots afterwards | `slot0 v1.0.0 active confirmed, slot1 v2.0.6` | the same | `slot0 v1.0.0 active confirmed, slot1 v2.0.5` |

So on this board the hang lasts at most the 30 s of MCUboot's watchdog, and the old version runs about 35 s after the jump for this 48 K image. A larger image takes longer to swap back: a swap took 56 s for an 840 K image in the first measurement series.

Full UART failure suite once, now 11 cases: **11 of 11**, no SMP timeout. The 10 older rows are the same as in the run before, apart from one byte in the image size of case 6. `tests/last_run.md`, `tests/logs/`.

Not tested: an image that calls `abort()` early instead of spinning, the same case over Bluetooth, and a hang with the debugger attached, where the IWDG can be frozen.

