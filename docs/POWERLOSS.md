# Power loss tests

Cutting the supply of the board at chosen moments of an update, and checking what it boots afterwards.

**Status of this page:** done. The test design was written and committed before any cut was run, and is unchanged. The results are at the end.

![Power loss test rig wiring](img/powerloss-rig.svg)

## Setup

The same wiring as text:

```
  bench supply 9 V, limit 500 mA                    laptop
   (+)        (-)                              USB        USB
    |          |                                |          |
    |          +-------------------+            |          |
    |                              |            |          |
  COM                              |     +------+------+   |
 [relay]  NO ----------------+     |     |   ESP32     |   |
    ^                        |     |     | WROOM-32    |   |
    | coil +, coil -, S      |     |     | devkit      |   |
    +---- VIN, GND, D26 -----|-----|-----+             |   |
                             |     |     +-------------+   |
                             v     v                       |
                        CN2 VIN   CN2 GND                  |
                      +-----------------------------+      |
                      |  B-L475E-IOT01A             |      |
                      |  JP4 on 5V_ARD (pins 3-4)   |      |
                      |  CN7 ST-LINK USB  ----------+------+
                      +-----------------------------+
```

- The relay sits in the positive supply line. Relay closed means the board is powered.
- The ESP32 only drives the relay. GPIO26 high closes it.
- The board's ST-LINK USB stays connected for flashing, resets and the console. It does not power the MCU in this jumper position.

Parts:

| Part | Used for |
|---|---|
| B-L475E-IOT01A | device under test |
| ESP32 WROOM-32 development board, on USB | relay controller, MicroPython 1.29.0 |
| Relay module with a JQC-3FF-S-Z 5 V coil, active high input | switches the supply |
| Bench supply, 9 V, current limit 500 mA | powers the board through VIN |
| Multimeter | the 3V3 reading with the relay open, see below |

Power facts and where they come from:

| Fact | Source |
|---|---|
| JP4 pins 3 and 4 select 5V_ARD, the supply from CN2 pin 8 (VIN) | UM2153 Rev 5, section 7.4 |
| The VIN input range is 7 to 12 V. The tests used 9 V | UM2153 Rev 5, section 7.4 |
| The board should be powered from the external source first, and the PC USB connected after that | UM2153 Rev 5, section 7.5 |
| The relay closes when its input is high | Checked by hand by the project owner |
| With the relay open the supply current drops to about 2 mA and the board goes dark | Observed by the project owner |
| With the relay open, CN2 3V3 to GND reads 300 mV | Multimeter reading by the project owner on 2026-10-07. A first reading the day before was reported only as "below 0.3 V" |
| The supply stayed in constant voltage mode during the runs and never showed C.C | Observed by the project owner. The script cannot see the supply |

The three UM2153 rows were read from the PDF of the manual by the project owner. They were not checked independently when this page was written.

**A deviation from the manual:** section 7.5 asks for external power first and USB second. In these tests the ST-LINK USB stays connected the whole time, while VIN is cut and restored by the relay. So at every restore the USB is already there when the external supply comes back. Whether that order matters for this board in this jumper position was not investigated.

Unverified, beyond the manual and the readings above: how fast the 3V3 rail falls after the relay opens, where the remaining 300 mV comes from, and what the MCU and the flash chips do while the rail falls.

## Safety check before the tests

| Relay | Console | OpenOCD |
|---|---|---|
| open | 0 bytes in 3 s | `Error: init mode failed (unable to connect to the target)` |
| closed | MCUboot and application banner | connects, target found |
| open again | 0 bytes in 3 s | cannot connect |

The MCU is off with the relay open.

### What the ST-LINK reports as target voltage

OpenOCD prints a "Target voltage" that it reads from the ST-LINK. Read 5 times in each relay state, `docs/data/powerloss_stlink_voltage.csv`:

| Relay | Reading 1 | 2 | 3 | 4 | 5 | Target |
|---|---|---|---|---|---|---|
| closed | 3.221 V | 3.221 V | 3.221 V | 3.221 V | 3.221 V | connects |
| open | 3.224 V | 3.218 V | 3.221 V | 3.221 V | 3.221 V | cannot connect |

The value is the same with the board powered and with it off, while the multimeter shows 300 mV on CN2 3V3 with the relay open. So in this setup this number does not tell whether the MCU is powered. **Why is unexplained.** No cause is claimed. The multimeter reading and the failing connection are what the safety check rests on.

The relay cannot stay closed by accident:

- The controller opens the relay at boot, on any error, and after 900 s without a command.
- `scripts/powerctl.py` opens it when the test script ends, also when it ends with an error.

## Relay controller

`tools/relay_controller/main.py`, MicroPython. Install with `scripts/powerctl.py install` on an ESP32 that runs MicroPython.

| Command | Effect | Reply |
|---|---|---|
| `ON` | close the relay | `OK` |
| `OFF` | open the relay | `OK` |
| `PULSE <ms>` | open for that long, then close | `OK` when done |
| `STATE` | | `OK ON` or `OK OFF` |

115200 baud, one command per line. Host side: `scripts/powerctl.py`, with `on()`, `off()`, `cycle(off_ms)` and a log of send and reply times.

## How exact is a cut

Measured with a test image that prints one character per millisecond: the time from sending `OFF` to the last character arriving. 10 runs, `docs/data/powerloss_latency.csv`.

| | Mean | Min | Max | Std dev |
|---|---|---|---|---|
| `OFF` sent to reply received | 8.9 ms | 8.4 ms | 9.4 ms | |
| `OFF` sent to console silent | 15.9 ms | 15.2 ms | 16.8 ms | 0.5 ms |

What this number is, and is not:

- It is host side timing. It contains the USB serial link to the ESP32, MicroPython handling the command, the relay opening, the supply rail falling, and the ST-LINK passing on the last characters.
- The relay contacts need a few milliseconds to move and they bounce. Neither was measured separately.
- The board has capacitors. The rail falls over some time, it is not an instant step to 0 V. The MCU keeps running for part of that time: about 14 characters still arrived after `OFF`.
- So an offset in the tables below is "the command was sent at this time". The MCU stopped roughly 16 ms later, give or take a few ms.
- When exactly a flash write in progress stops being valid during the fall is not known.

## Test design

Written before running.

Each case: reset the board to the known baseline (mass erase, flash MCUboot and v1.0.0, erase slot 1, check the slot state), bring it to the chosen moment, send `OFF`, wait 2 s, send `ON`, then watch the console and read the slot state.

| Phase | The moment of the cut | Cuts | Expected |
|---|---|---|---|
| a. Upload | While v2.0.0 is uploaded, at about 25, 50 and 75 percent | 6: each twice | v1.0.0 still runs |
| b. Swap | During the test swap from v1.0.0 to v2.0.0. Offset counted from the first MCUboot console line after the reset | 32: a sweep of 20 offsets from 100 to 4300 ms, and 12 random offsets between 0 and 4500 ms | a valid image, old or new |
| c. Revert | During the revert swap, after a v2.0.1 image that fails its health check. Offset from the first MCUboot line | 6: 300, 1000, 1800, 2600, 3400, 4200 ms | a valid image, old or new |
| d. Confirm | Around the moment the application confirms v2.0.0, 5 s after its banner. Offset from the banner | 6: 4900, 4960, 5000, 5040, 5100, 5300 ms | v2.0.0 confirmed, or reverted to v1.0.0 |
| e. Erase | During an erase of slot 1 that holds an image | 5: 500, 2000, 5000, 9000, 13000 ms after the request | v1.0.0 still runs |

- Random offsets come from Python's `random.Random(20261006)`. The seed is in every CSV row.
- 55 cuts in total by this plan. 5 more were added after the run, see "Results". The swap of this image takes about 4.4 s from the first MCUboot line to the application.
- The image is the 47.9 K one. The swap only moves the sectors the image uses.

### What is recorded per cut

`docs/data/powerloss_runs.csv`: phase, sweep or random, seed, the offset asked for and the offset at which `OFF` was really sent, the last MCUboot stage seen on the console before the cut, the version running after power came back, whether it booted without help, the time from `ON` to the application banner, the final slot state, and the console lines that prove it. The full console log of each cut is in `tests/logs_powerloss/`.

### What counts as a pass

All of these, for every cut:

1. **It boots without help.** The application banner appears within 120 s of `ON`, with nothing done to the board.
2. **It runs the old or the new version**, nothing else.
3. **It settles.** After the health window the running image is confirmed. A test image that confirms itself counts, and so does a revert to the old one.
4. **The image in slot 0 is complete.** Slot 0 is read back over SWD and compared byte for byte with the signed image file of the version that is running. This does not rely on MCUboot's own check.
5. **It boots a second time.** After a normal reset the same version comes up again, confirmed.

A board that boots but fails 4 or 5 is a failure. That is what would catch a half finished swap that happens to start.

Also recorded, not part of pass or fail: whether the update ended on the new or the old version. A cut that leaves the old version running is safe, and the update is lost.

MCUboot is built with `CONFIG_BOOT_VALIDATE_SLOT0=y`, so it checks the hash and signature of slot 0 at every boot. Check 4 is there so that the result does not depend on that.

### If a cut leaves the board unable to boot

It is recorded as a failure with its console log. The board is then recovered with a mass erase and a reflash over the ST-LINK, which the baseline step does anyway, and the run continues. Nothing is retried to turn a failure into a pass.

## Results

Run on 2026-10-06. Raw data: `docs/data/powerloss_runs.csv`, 60 rows. Console proof per cut: `tests/logs_powerloss/`.

| Phase | Cuts | Passed | Ended on the new version | Ended on the old version | Time from power on to the application |
|---|---|---|---|---|---|
| a. Upload | 6 | 6 | 0 | 6 | 0.61 s |
| b. Swap | 37 | 36, and 1 not valid, see below | 27 | 9 | 0.72 to 4.89 s |
| c. Revert | 6 | 6 | 0 | 6 | 0.72 to 4.87 s |
| d. Confirm | 6 | 6 | 4 | 2 | 0.59 to 4.88 s |
| e. Erase | 5 | 5 | 0 | 5 | 0.61 to 0.62 s |
| **Total** | **60** | **59** | | | |

**No cut left the board unable to boot, and no manual recovery was needed.** In all 59 valid cuts slot 0 matched the signed image byte for byte, and the board booted a second time into the same confirmed version.

What happened in each phase:

- **Upload.** The old image started 0.61 s after power came back, as on a normal boot. `Swap type: none`.
- **Swap, cut while it runs** (`OFF` sent 0.10 to 4.10 s after the first MCUboot line, 27 cuts). MCUboot continued the swap after power came back and booted v2.0.0, which then confirmed itself. The later the cut, the less was left to do: 4.70 s to the application after a cut at 0.10 s, 0.72 s after a cut at 4.10 s.
- **Swap, cut after it finished** (`OFF` sent 4.18 to 4.51 s, 9 cuts). The swap was complete and v2.0.0 was about to start or had just started, unconfirmed. After power came back MCUboot did what it does with any unconfirmed image after a reset: `Swap type: revert`, and v1.0.0 ran. The device is safe, the update is lost and has to be sent again.
- **Revert.** A cut during the revert swap: MCUboot continued the revert, v1.0.0 ran.
- **Confirm.** Cuts at 4.90 and 4.97 s after the banner came before the confirm: the image was reverted to v1.0.0. Cuts at 5.01 s and later came after it: v2.0.0 stayed, confirmed. No cut landed in a state in between.
- **Erase.** v1.0.0 started normally. Slot 1 was left partly erased, and the next baseline erased it again without trouble.

### The one cut that is not valid, and two mistakes in the test harness

Both were mistakes in the test script, not in the board. They are listed because they changed what the first numbers looked like.

1. **Row 38, swap, offset 4463 ms: recorded as failed.** The banner of v2.0.0 reached the host just after `OFF` was sent. The script took it for the banner after power came back, noted "v2.0.0", and then compared slot 0 with the v2.0.0 file. The console log of that cut shows what really happened: `Swap type: revert`, then `OTA app v1.0.0 ... confirmed`, and the slot state read afterwards was `slot0 v1.0.0 active confirmed, slot1 v2.0.0`. So the board behaved like the other late cuts. But checks 4 and 5 were made against the wrong version, so this row proves nothing and stays marked as failed. The script was corrected to count only lines that arrive after `ON`, and the same offset was run three more times, plus 4400 and 4500 ms (rows 56 to 60). All five passed, ending on v1.0.0.

2. **A first attempt was stopped after 8 cuts.** All six upload cuts were marked failed on check 4. The cause: the baseline is flashed from the `.hex` file and the script compared slot 0 with the `.bin` file. The build signs those two separately and an ECDSA signature is different every time, so they differ in their last bytes (from byte 47814 of 47963). The reference was corrected to the file that is actually flashed and the whole run was started again. The 8 rows of the stopped attempt are in `docs/data/powerloss_first_attempt.csv`.

Neither correction changed a pass criterion.

### Timing of the cuts

- `OFF` was sent 8.5 ms later than the planned offset on average, 20.1 ms at most. The CSV has both the planned and the real offset.
- Add about 16 ms from `OFF` to the board going silent, from the latency measurement above.

### What this does and does not show

It shows that on this board, with this image, a clean 2 s loss of supply at 60 moments of an update never left it without a bootable, complete image.

It does not show:

- That it holds for other image sizes. Only the 47.9 K image was used. A swap of a large image is longer and touches more sectors.
- That there is no bad window shorter than the spacing of the cuts. 37 cuts over 4.5 s is one per 120 ms on average, against flash operations that take milliseconds.
- Anything about a slow brown out, short glitches, or several cuts in a row.
- Anything measured about the supply. That it stayed in constant voltage mode was observed by eye, not logged.
- Anything about another board, another flash chip, or another MCUboot version. The swap here uses MCUboot's logical sector option, which is marked experimental upstream.

## Limits

- One board, one image size (47.9 K), one supply voltage, room temperature.
- The cut is not sharp: about 16 ms from command to silence, with relay bounce and a falling rail inside that.
- 2 s off time only. No short glitches, no slow brown out, no repeated cuts during one swap.
- A cut during the resumed swap after a first cut was not tested.
- The external flash loses power together with the MCU. A case where only one of them resets is covered by the reset tests, not here.
- The script does not monitor the bench supply. That it never went into current limiting comes from the project owner watching it.
- The ST-LINK reports about 3.22 V as target voltage whether the board is powered or not. Unexplained, see above.
- With the relay open, 300 mV remain on the 3V3 rail. The source was not investigated. The MCU does not run at that voltage in these tests, but the rail does not reach 0 V, so this is not a cut to zero.
- The power sequence differs from the one the manual asks for: the ST-LINK USB is connected before the external supply returns.
- 32 cuts in a 4.4 s swap is one cut per 140 ms on average. A window shorter than that can be missed.
