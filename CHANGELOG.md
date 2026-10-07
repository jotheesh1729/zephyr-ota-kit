# Changelog

All notable changes to this project. Versions follow semantic versioning. Dates are ISO 8601.
Nothing has been tagged or released yet.

## [0.1.0] - unreleased

First version. Developed and tested on an ST B-L475E-IOT01A (`disco_l475_iot1`), then on an ESP32 WROOM-32 dev board (`esp32_devkitc`), with Zephyr `133c2eb7d3cb`, MCUboot `7ad67106` and hal_espressif `5e3b702250`.

### Added

- **Zephyr module "OTA kit"** (`zephyr/module.yml`, `Kconfig`, `src/`, `include/ota_kit/`).
  - SMP server for image upload, image state and reset, selected by `CONFIG_OTA_KIT`.
  - Health check hook `ota_kit_set_health_check()`. A test image is confirmed only if the registered check returns true.
  - Watchdog armed before `main()` and fed by a health thread, so a hung image is reset and reverted.
  - Transport choice: UART, Bluetooth LE, or set up by the application.
  - Bluetooth LE transport with an encrypted link, stored bond and a fixed address.
  - Size guard: the build fails if the image is larger than MCUboot can swap with swap using move.
  - Build check for a missing flash reset command on an STM32 QSPI flash.
- **Sysbuild integration** (`sysbuild/`, snippets `ota-kit` and `ota-kit-ble`): MCUboot with swap using move and ECDSA P256, MCUboot watchdog timeout, logical sector size, downgrade prevention.
- **Board support for `disco_l475_iot1`**: slot 0 resize, 4 K logical sectors, QSPI flash reset at init, 30 s MCUboot watchdog timeout.
- **Board support for `esp32_devkitc`** (ESP32 WROOM-32). Wi-Fi is supported, UART is partial, Bluetooth is not tested, see `docs/BOARD_ESP32.md`.
  - Wi-Fi: kit option `OTA_KIT_WIFI_UDP` and snippet `ota-kit-wifi` add SMP over UDP next to the UART. `scripts/wifi_provision.py` stores the network on the board, not in the build. SMP shell commands are refused once a network is stored.
  - The kit sets `CONFIG_BOOT_VALIDATE_SLOT0=y` in MCUboot. MCUboot's ESP32 configuration turns it off.
  - The watchdog is the one of timer group 1 and MCUboot starts it with 30 s, so an image that dies before `main()` is reset and reverted.
  - `UART_MCUMGR_RX_BUF_COUNT` defaults to 8. With 2, SMP requests over UART went unanswered in 3 of 40 uploads.
  - Optional `west patch` for the Espressif HAL, `zephyr/patches.yml`: the cache flush proposed in Zephyr issue 120719. A data word that moves the link layout is the fallback without it, and is fragile.
  - Not on this board: the size guard (Cortex-M only) and the fixed Bluetooth address.
- **Host tools**
  - `scripts/build.sh`: versioned builds, `BOARD=`, `VARIANT=ble` or `wifi`, `ENC=1` for encrypted images.
  - `scripts/ota_update.py`: upload, test, reset, watch the confirm, report timings. UART, BLE or UDP.
  - `scripts/wifi_provision.py`: stores a Wi-Fi network on the board without showing or saving it on the host.
  - `scripts/ota_doctor.py`: 23 rules that check a finished build for OTA configuration mistakes. Text and JSON output.
  - `scripts/static_analysis.py`: cppcheck with its MISRA addon on this project's C files.
- **Tests**
  - Hardware failure suite, 11 cases (case 9, a hang before `main()`, added last): good update, failed health check, wrong key, raw binary, missing signature, corrupted image, interrupted upload, downgrade, hang, reset during flash erase.
  - Measurement script for repeated updates, `tests/uart_soak.py` for repeated uploads that record every failed request, and a reset sweep through a slot erase for the ESP32.
  - Power loss tests: a relay controller (MicroPython on an ESP32), `scripts/powerctl.py`, and `tests/powerloss.py`, which cuts the supply during upload, swap, revert, confirm and erase.
  - Doctor tests on fixtures captured from real builds, and a check for home directory paths. Both run in CI.
- **Examples**: `app/` for `disco_l475_iot1` and `esp32_devkitc`, `samples/minimal` for `native_sim` and, compile only, `nrf52840dk`.
- **Documentation**: setup, results with raw data, porting guide, doctor rules, transports, requirements with traceability, hazards, code quality and deviations, related work, findings for upstream.

### Measured on the boards

ST B-L475E-IOT01A:

- UART: 20 of 20 updates, 18.38 s mean from upload start to confirmed, for a 47.9 K image.
- Bluetooth LE: 20 of 20 and later 5 of 5 updates, 53.67 s and 56.05 s mean, for a 120 K image.
- Failure suite: every case as expected on UART (11 cases) and on BLE (9 cases). A raw binary is refused at upload rather than by MCUboot.
- Hang recovery: watchdog reset 10.1 s after a hang in `main()`, and 29.8 s after a hang before `main()`, then revert, in every run.
- Power loss: 60 cuts, the board booted a complete image without help every time. 59 rows pass, 1 is not valid because of a test script mistake.

ESP32 WROOM-32:

- Wi-Fi: 30 of 30 updates, 31.0 s median from upload start to confirmed, for a 682 K image. Failure suite clean in three passes (9, 9 and 10 cases).
- An image that aborts or hangs before `main()`: reset by the watchdog after about 29 s and reverted, 3 of 3 runs. Before the watchdog change the board stayed dead until an outside reset, 3 of 3.
- UART: updates work. Before the buffer change 3 of 40 uploads had an unanswered request, after it 1 in about 100.

### Known limits

- Two boards on hardware, one of each. Other boards are compile tested at most.
- The debug port is open and readout protection is off. On the ESP32 there is no secure boot and no flash encryption.
- Power loss was tested only on the STM32, as a clean 2 s cut with a 47.9 K image. No brown out, no glitches, no large image.
- No safe state check before the device reboots for an update.
- SMP over UART and over UDP have no authentication, and UDP no encryption. Bluetooth pairing does not authenticate the central.
- The Wi-Fi network name and passphrase are stored on the ESP32 in plain text.
- Image encryption is optional, not enforced, and its key can be read from a device whose flash is readable.
- The watchdog does not catch a hang in the SMP thread or in lower priority threads. On the ESP32 a short gap is left while the application takes the watchdog over.
- ESP32: an upstream fault in the early flash init can produce an image that aborts before `main()`. The fix is not merged upstream and is carried as an optional patch.
- ESP32 over UART: one unanswered request in about 100 uploads, cause not found. Bluetooth on the ESP32 has no suite run.
- Wi-Fi was tested on one afternoon on one network, with the laptop close by.
- Wi-Fi does not work as a transport on the STM32 board.
- MCUboot's logical sector option, which the STM32 layout needs, is marked experimental upstream.
- Not a certified product, and not a MISRA compliance claim.
