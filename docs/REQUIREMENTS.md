# Requirements and traceability

What the kit is supposed to do, where that is implemented, and which test shows it.

- Every result below is from `disco_l475_iot1`. Evidence is named by the test series it comes from, each one a section of [RESULTS.md](RESULTS.md).
- A requirement is only called tested if a test in this repository was run on the board, or, where marked "build", on a real build.
- "Not tested" means exactly that. Those rows are listed on purpose.
- This is a traceability table for a demonstration project. It is not a safety case.

## Tested on hardware

| ID | Requirement | Implemented in | Test | Result |
|---|---|---|---|---|
| OTA-REQ-001 | An image only boots if it carries a valid ECDSA P256 signature made with the project key | MCUboot, configured by `snippets/ota-kit/ota-kit-sb.conf` | Cases 3 (wrong key), 4b (no signature), 5 (corrupted) in `tests/run_tests.py` | PASS. 5 passes in the first measurement series, again in the QSPI reset fix, the module build and the final firmware series on UART, the first BLE series and the BLE regression on BLE |
| OTA-REQ-002 | A file without an MCUboot header is not accepted as an update | Zephyr image manager, enabled by `CONFIG_OTA_KIT` in `Kconfig` | Case 4 (raw binary) | PASS, refused at upload. The failure handling tests explains the path |
| OTA-REQ-003 | A new image runs in test mode and becomes permanent only after the application's health check returned true | `src/ota_kit.c`, `health_thread()` and `ota_kit_set_health_check()` | Case 1 (good) | PASS. 20 of 20 measured runs in the final firmware series |
| OTA-REQ-004 | An image whose health check fails is reverted at the next reset | `src/ota_kit.c`, MCUboot swap using move | Case 2 (nohealth) | PASS. The failure handling tests, the first measurement series, the module build and the final firmware series |
| OTA-REQ-005 | An image that hangs is reset by the watchdog and reverted, with no outside action | `src/ota_kit.c`, `watchdog_start()`, feeder priority | Case 8 (hang) | PASS, chip reset 10.1 s after the hang in every run. The failure handling tests, the first measurement series, the module build and the final firmware series |
| OTA-REQ-006 | An upload that is cut off leaves the running image untouched | MCUboot slot layout, Zephyr image manager | Case 6 (interrupted at 50%) | PASS. The failure handling tests, the first measurement series, the module build and the final firmware series |
| OTA-REQ-007 | An image with a lower version than the running one is rejected | `sysbuild/CMakeLists.txt`, `SB_CONFIG_OTA_KIT_DOWNGRADE_PREVENTION` | Case 7 (downgrade) | PASS, rejected at boot, not at upload. The final firmware series |
| OTA-REQ-008 | A reset during an erase of the external flash does not delay the next boot | `snippets/ota-kit/boards/disco_l475_iot1.overlay`, `reset-cmd` | Case 10 (reset in erase) | PASS, 0.6 s. It was 30.6 s before the fix. The QSPI reset fix |
| OTA-REQ-009 | An image larger than MCUboot can swap cannot be built | `linker/size_guard.ld`, `CONFIG_OTA_KIT_SIZE_GUARD` | Manual, the final firmware series: build an 879091 B image, and update with an 876527 B image | PASS. The first does not build, the second swaps and confirms |
| OTA-REQ-010 | MCUboot's watchdog timeout is within what the hardware can do, and the watchdog survives a long swap | `snippets/ota-kit/boards/disco_l475_iot1-sb.conf`, 30000 ms | Boot log has no `Watchdog install timeout failed`, and the near full slot run | PASS. A 56 s swap completed with a 30 s timeout. The failure handling tests, the first measurement series and the final firmware series |
| OTA-REQ-011 | Over BLE, the SMP service is only usable on an encrypted link | `Kconfig`, `CONFIG_OTA_KIT_TRANSPORT_BLE` and the permission default | The first BLE series: 0 of 5 sessions before pairing, 5 of 5 after | PASS, once, by hand. Not a case in the suite |
| OTA-REQ-012 | Over BLE, a bond survives a reset of the board | `src/ota_kit_ble.c`, fixed address and settings | Every BLE update: the host reconnects after the reset without pairing | PASS. The first BLE series and the BLE regression |
| OTA-REQ-013 | With encrypted updates, the update file does not contain the plain image | `scripts/build.sh` `ENC=1`, MCUboot | The final firmware series: file comparison, one update | PASS, 1 run |
| OTA-REQ-014 | With encrypted updates, a rollback still restores the old image | MCUboot | The final firmware series: encrypted image that hangs | PASS, 1 run |
| OTA-REQ-030 | A loss of power during a swap, a revert or the confirm does not leave the device without a bootable, complete image | MCUboot swap using move with logical sectors, configured by `snippets/ota-kit` | `tests/powerloss.py`, phases swap, revert and confirm: 49 cuts | 48 PASS, 1 row not valid because of a test script mistake. No board lost. The power loss tests. One image size, clean cuts only |
| OTA-REQ-031 | A loss of power during an upload or a slot erase leaves the running image untouched | MCUboot slot layout | `tests/powerloss.py`, phases upload and erase: 11 cuts | PASS, 11 of 11. The power loss tests |

## Checked on a build, not on hardware

| ID | Requirement | Implemented in | Check | Result |
|---|---|---|---|---|
| OTA-REQ-020 | MCUboot fits its partition | board devicetree, MCUboot configuration | Linker, and doctor rule SIZE-02 | PASS, 40512 of 65536 B (61.8%). With encryption 45808 B |
| OTA-REQ-021 | The build stops if slot 1 is on an STM32 QSPI flash without `reset-cmd` | `src/ota_kit.c`, `BUILD_ASSERT` | Seen once by accident in the module build, and doctor fixture `no_reset_cmd` | PASS |
| OTA-REQ-022 | A build without a registered health check is reported | `scripts/ota_doctor.py`, rule HEALTH-01 | Doctor fixture `no_health_check` | PASS on the build. The behaviour on the board, no confirm and a revert, was not run |
| OTA-REQ-023 | A build with a forced failure option is marked as a test image | `app/src/main.c`, `#warning` | Build logs of the hang and nohealth images contain the warning | PASS. The doctor rule HEALTH-02 for these options has no fixture |
| OTA-REQ-024 | Common configuration mistakes are reported before flashing | `scripts/ota_doctor.py` | `tests/doctor`, 9 tests on 16 fixtures, in CI | PASS |

## Not tested

| ID | Requirement | Why it matters | Status |
|---|---|---|---|
| OTA-REQ-038 | The device survives a slow fall of the supply (brown out), short glitches, or a second cut during a resumed swap | The power loss tests only used a clean 2 s cut | **Not tested** |
| OTA-REQ-039 | A loss of power during the swap of a large image is survived | Only the 47.9 K image was cut. A large image swaps for up to 56 s | **Not tested** |
| OTA-REQ-032 | An image with the same version as the running one is handled in a defined way | Downgrade prevention compares versions. What it does on equality was read in the source, not run | **Not tested** |
| OTA-REQ-033 | Over BLE, a second central cannot pair once one is bonded | The board keeps one bond and does not overwrite it, by configuration | **Not tested.** No second central was available |
| OTA-REQ-034 | An update is only started when the device is in a state where a reboot is acceptable | The kit resets when the host says so | **Not implemented.** There is no hook for the application to refuse or defer |
| OTA-REQ-035 | A hang in the SMP thread or in lower priority threads is detected | The watchdog feeder runs above them by design | **Not covered by design**, see the failure handling tests |
| OTA-REQ-036 | The keys in the device cannot be read out | Readout protection is off on the board | **Not implemented** |
| OTA-REQ-037 | The failure cases behave the same with encrypted images | Only one update and one rollback were run with encryption | **Not tested** as a suite |
