# Reference

Results in short, the security model, the options, the known limits and the repository layout.
The [README](../README.md) tells you how to use the kit. This file holds the facts behind it.
Numbers are from the ST B-L475E-IOT01A unless a line says otherwise. The ESP32 numbers are in [BOARD_ESP32.md](BOARD_ESP32.md).

## What it does

| Situation | Outcome | Measured |
|---|---|---|
| Valid signed update | Boots in test mode, passes a health check, confirms itself | 20 of 20 runs, 18.3 s mean |
| Wrong key, no signature, or flipped bytes | MCUboot refuses it, old image keeps running | 15 of 15 |
| Image runs but fails its health check | Reverted at the next reset | 5 of 5 |
| Image hangs at boot | Watchdog resets the chip, MCUboot reverts, no outside help | 5 of 5, reset after 10.1 s |
| Upload killed halfway | Old image keeps running | 5 of 5 |
| Reset in the middle of a flash erase | Boots normally in 0.6 s | was 30.6 s before the fix |

## Architecture

```
  Host (Linux)                               Board (B-L475E-IOT01A)
 +----------------------+                   +--------------------------------------+
 | scripts/build.sh     |                   |  MCUboot (64 K, internal flash)      |
 |   west + sysbuild    |                   |   - verifies ECDSA P256 signature    |
 |   imgtool sign       |                   |   - swap using move, revert if the   |
 |   (ECDSA P256 key)   |                   |     image was not confirmed          |
 +----------+-----------+                   |   - starts the IWDG at 30 s          |
            | signed image                  +------------------+-------------------+
            v                                                  | boots
 +----------------------+   SMP over UART   +------------------v-------------------+
 | scripts/ota_update.py|  (ST-LINK VCP,    |  App (slot 0, internal flash)        |
 |   1 upload           |   115200 baud)    |   - SMP server: upload, state, reset |
 |   2 mark for test    +------------------>|   - writes the new image to slot 1   |
 |   3 reset            |                   |   - health thread: feeds the IWDG,   |
 |   4 watch console    |<------------------+     confirms after 5 s if healthy    |
 |   5 read slot state  |   console + SMP   +------------------+-------------------+
 +----------------------+                                      | QSPI
                                            +------------------v-------------------+
                                            |  Slot 1 (external MX25R6435F flash)  |
                                            |   staged update, or previous image   |
                                            +--------------------------------------+
```

Update sequence:

```
upload -> slot 1 -> mark "test" -> reset
   -> MCUboot: signature ok? --no--> erase slot 1, boot old image
                 | yes
                 v
        swap slot 0 and slot 1, boot new image once
                 |
        runs 5 s, health check ok? --yes--> confirm, image is permanent
                 | no, or hung (watchdog reset after 10 s)
                 v
        next boot: MCUboot swaps back, old image runs
```

## Security model

Protected:

- **Authenticity and integrity of what boots.** MCUboot verifies an ECDSA P256 signature over a SHA256 of the image, on every boot and before every swap. Tested with a wrong key, no signature, and corrupted payload.
- **Availability after a bad update.** Test boot, self confirm, and revert. Tested with a failing health check and with a hang.
- **The signing key.** The private key stays on the build host and is not in git. Only the public key is in the bootloader.

Not protected:

- **The bootloader itself.** Readout protection is off (RDP level 0) and the debug port is open. Anyone with a probe can replace MCUboot and its public key. There is no hardware root of trust.
- **Downgrade by debug probe.** MCUboot refuses an image with a lower version than the running one (tested, rejected at boot). Someone with a probe can still write any version.
- **Confidentiality, by default.** Updates are not encrypted unless built with `ENC=1`. Even then MCUboot keeps the private key in its own flash, and on this board that flash is readable. See "Encrypted images" in docs/RESULTS.md.
- **The UART transport.** SMP on the UART has no authentication. Anyone on the port can upload, erase slot 1, or reset the board. They cannot make an unsigned image boot.
- **The Wi-Fi transport on the STM32 board.** The board opens a UDP socket to a host address that is fixed at build time, with no encryption and no authentication. Whoever answers at that address, or can send from it, can upload, erase slot 1, reset the board and read the installed versions. An update can be read on the network. An image that is not signed with the owner's key still does not boot. The network name and passphrase are stored on the board in plain text. See [TRANSPORTS.md](TRANSPORTS.md).
- **The Wi-Fi transport (ESP32, SMP over UDP).** No encryption and no authentication. Anyone on the same network can upload a file, erase slot 1, reset the board and read the installed versions, and can see an update in clear text. They cannot make an image boot that is not signed with the owner's key, and they cannot run shell commands. The network name and passphrase are stored on the board in plain text. See HAZ-16 and HAZ-17 in [docs/HAZARDS.md](HAZARDS.md).
- **The BLE transport, partly.** The link is encrypted and SMP needs a paired central. But pairing is "Just Works": it does not prove who the central is, and it has no protection against a man in the middle. The board keeps a single bond, so the first device to pair should be the only one accepted until the storage is erased. That lockout was not tested, and before the first pairing anyone in range can take the slot. Passkey pairing is not implemented.
- **The key at rest.** It is an unencrypted PEM file on the build host. This is a development key.

## Quality and safety documents

| Document | What it is |
|---|---|
| [docs/REQUIREMENTS.md](REQUIREMENTS.md) | Requirements with IDs, traced to the source file and the test that shows each one. Untested ones are listed as such |
| [docs/HAZARDS.md](HAZARDS.md) | What can go wrong with an update, the mitigation, the evidence, and the risk that remains |
| [docs/QUALITY.md](QUALITY.md) | Static analysis of this project's own C code with cppcheck and its MISRA addon, strict compiler warnings, and CI |
| [docs/DEVIATIONS.md](DEVIATIONS.md) | The findings that were not fixed, with reason and risk |

These follow the style of functional safety practice: requirements, traceability, known gaps written down. **They are not a certification and not a MISRA compliance claim, and no ASIL is claimed.**

What runs automatically and what does not:

- **CI, on every push:** the doctor tests, a check for home directory paths, a native_sim build of the module, and the static analysis of that build.
- **By hand, on the board:** the board build, the failure suite, the measurements, and everything over BLE. Hardware tests are not in CI. The results in this README are from manual runs on one `disco_l475_iot1`.

## Reproduce the tests

After the quick start, on the board:

```sh
tests/build_images.sh        # baseline and every test image
tests/run_tests.py           # failure suite, about 10 minutes
tests/measure.py 20          # 20 measured updates and one near full slot update
```

For Bluetooth LE: `VARIANT=ble tests/build_images.sh`, then set `transport = "ble"` in `tests/config.toml`.
`scripts/build.sh` expects the workspace at `~/zephyrproject`, or set `ZEPHYR_BASE`.

## Results

Measured on the STM32 board on 2026-10-05. The ESP32 numbers are in [docs/BOARD_ESP32.md](BOARD_ESP32.md). Full tables, logs and limits are in [docs/RESULTS.md](RESULTS.md). Raw data is in `docs/data/`.

Update flow over UART, 20 runs, 47.9 K signed image, built through the module:

| Metric | Min | Mean | Max |
|---|---|---|---|
| Upload over UART | 8.44 s | 8.48 s | 8.60 s |
| MCUboot verify + swap | 4.37 s | 4.39 s | 4.40 s |
| Total, upload start to confirmed | 18.34 s | 18.38 s | 18.49 s |
| Success | | 20 of 20 | |

The total includes a fixed 5 s health window.

Near full slot image, 840 K (97.65% of the slot): upload 138 s, MCUboot verify + swap 56 s, total 200 s.

Failure cases, 5 passes each:

| Case | Expected | Result |
|---|---|---|
| Good image | Swap, confirm | 5 of 5 |
| Never confirms | Revert after reset | 5 of 5 |
| Signed with the wrong key | Rejected by MCUboot | 5 of 5 |
| Raw binary, no header | Rejected by MCUboot | 5 of 5, but refused earlier, at upload, by the app |
| Header and hash, no signature | Rejected by MCUboot | 5 of 5 |
| Flipped payload bytes | Rejected by MCUboot | 5 of 5 |
| Upload killed at 50% | Old image runs | 5 of 5 |
| Hang at boot | Watchdog reset, revert | 5 of 5 |
| Reset during a flash erase | Normal boot | 2 of 2 after the fix |
| Power cut during upload, swap, revert, confirm or erase | Boots a complete image, old or new, without help | 59 of 60 cuts, the other one is a test script mistake |
| Power cut after the swap finished, before the new image confirmed itself | Reverts to the old version. The update is lost and must be sent again | 11 of 11 such cuts ended on the old version |
| Older version offered again | Rejected by MCUboot | 1 of 1, at boot |
| Image too large to swap | Cannot be built | build fails with a clear message |

Over Bluetooth LE, 20 runs, 119.7 K signed image (the BLE stack makes the image 72 K larger):

| Metric | Min | Mean | Max |
|---|---|---|---|
| Upload over BLE | 32.49 s | 33.60 s | 36.27 s |
| MCUboot verify + swap | 7.46 s | 7.81 s | 8.23 s |
| Total, upload start to confirmed | 52.33 s | 53.67 s | 56.75 s |
| Success | | 20 of 20 | |

Throughput is about 3.6 kB/s on BLE against 5.7 kB/s on UART. The failure suite gave the same result over BLE as over UART, in one pass.
The BLE numbers are from before the code became a module. On the module build two BLE cases were rerun as a smoke test.

Size:

| Image | Flash | RAM |
|---|---|---|
| MCUboot | 40512 B of 64 K | 15552 B |
| MCUboot, with image encryption | 45808 B of 64 K | 15936 B |
| Application, UART | 47780 B | 15104 B |
| Application, with BLE | 117680 B | 34014 B |

## Options

| Option | Default | What it does |
|---|---|---|
| Size guard | on | The build fails if the image is larger than MCUboot can swap |
| Downgrade prevention | on | MCUboot refuses an image with a lower version |
| Bluetooth LE | off, `VARIANT=ble` | SMP over an encrypted BLE link instead of UART |
| Encrypted images | off, `ENC=1` | The update file and slot 1 are encrypted. Not enforced, and no protection on a readable device |

## Three things found on the hardware

1. **MCUboot's watchdog never started.** It asks for a 300 s timeout and the STM32L4 IWDG tops out near 32.8 s, so the driver refused it with a one line error at boot. Setting 30 s fixed it. A 56 s swap then showed that MCUboot really feeds it.
2. **The watchdog fired in the middle of a flash erase.** A whole slot erase busy polls the QSPI flash for about 15 s and starved a low priority feeder thread. The feeder now runs just above the SMP thread.
3. **A reset during a flash erase stalled the boot for 30 s.** The MCU reset does not reset the external flash, which stays busy. The driver now sends the flash reset command at init, with the 12 ms recovery time from the datasheet. Boot went from 30.6 s to 0.6 s.

## Known limits

- Power loss was tested with clean 2 s cuts on a 47.9 K image only. No brown out, no glitches, no large image.
- A power cut after the swap and before the confirm, a window of about 5 s, makes MCUboot revert to the old version. The device stays usable, but the update did not happen and must be sent again. Nothing on the device retries it.
- No secure boot chain below MCUboot and no readout protection. Image encryption exists as an option, but it is not enforced and the key is readable from the device.
- MCUboot's logical sector option, which this layout depends on, is marked experimental upstream.
- The watchdog does not catch a hang in the SMP thread or in lower priority threads. A per thread watchdog (`task_wdt`) is the planned fix.
- The health check is shallow: watchdog armed, LED ready, slot 1 flash reachable.
- The failing health check and the hang are forced by build options, not real faults.
- Downgrade prevention rejects an older image at boot, after it was uploaded. The SMP server does not refuse the upload.
- Upload is slow, about 5.7 kB/s on a 115200 baud UART and about 3.6 kB/s on BLE.
- BLE pairing does not authenticate the central. See the security model.
- One board of each kind, a few days of measurements, host side timing.
- The ESP32 has its own list of limits: [docs/BOARD_ESP32.md](BOARD_ESP32.md), and the changelog under "Known limits".

## Repository

```
zephyr/module.yml         makes this repository a Zephyr module, the OTA kit
zephyr/patches.yml        optional patch for the Espressif HAL, for "west patch"
west.yml                  optional west manifest: Zephyr pinned to the tested revision
Kconfig, CMakeLists.txt   the options and the build file of the module
src/, include/            the kit: health thread, confirm, watchdog, BLE advertising, Wi-Fi join,
                          the dial-out transport
linker/                   the size guard
sysbuild/                 the sysbuild options of the kit, applied to MCUboot and the application
snippets/                 ota-kit, ota-kit-ble, ota-kit-wifi, ota-kit-wifi-dial, and the board files
app/                      example application: LED blink, health check, test options
samples/minimal/          smallest application that uses the kit
keys/                     your signing key goes here, it is not in the repository
scripts/                  build.sh, ota_update.py, ota_doctor.py, wifi_provision.py, udp_relay.py,
                          static_analysis.py, powerctl.py
tools/                    relay controller for the power loss tests (MicroPython, ESP32)
tests/                    build_images.sh, run_tests.py, measure.py, uart_soak.py, powerloss.py,
                          config.toml, the last result tables and the logs of the runs
  doctor/                 tests and fixtures for ota_doctor.py, no hardware needed
docs/                     one file per topic, data/ (raw CSV), img/ (diagrams), release/
```

A 60 second demo script is in [DEMO.md](DEMO.md).

How this compares to existing tools: [RELATED_WORK.md](RELATED_WORK.md).
