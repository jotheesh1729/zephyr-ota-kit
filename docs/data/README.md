# Raw measurement data

Every file is the unedited output of `tests/measure.py` or `tests/run_tests.py --repeat` on a `disco_l475_iot1`.
Files without a suffix hold the latest run and are overwritten by the next one.

| File | From | Described in |
|---|---|---|
| `update_runs_before_qspi_fix.csv`, `big_image_run_before_qspi_fix.csv` | First 20 UART runs, before the QSPI reset fix | RESULTS.md, "Measurement", the note under the table |
| `update_runs_after_qspi_fix.csv`, `big_image_run_after_qspi_fix.csv` | 20 UART runs after the QSPI reset fix | RESULTS.md, "Measurement", the table |
| `update_runs_module_build.csv`, `big_image_run_module_build.csv` | 20 UART runs, kit built as a module | The module build |
| `update_runs.csv`, `big_image_run.csv` | 20 UART runs on the final firmware | The final firmware series |
| `failure_runs.csv` | Failure suite, 5 passes, before the QSPI reset fix | The first measurement series |
| `update_runs_ble_first_series.csv` | 20 BLE runs | The first BLE series |
| `update_runs_ble.csv` | 5 BLE runs on the final firmware | The BLE regression |

| `esp32_uart_soak_baseline.csv`, `esp32_uart_soak_rxbuf8.csv`, `esp32_uart_soak_frame254.csv` | ESP32, `tests/uart_soak.py`: 40 uploads with 2 SMP line buffers, 20 with 8, 22 with small frames | BOARD_ESP32.md, "UART defect" |
| `failure_runs_esp32.csv` | ESP32 failure suite, two passes on 2026-10-07 with the new cable. The file of the day before was replaced, its results are in BOARD_ESP32.md | BOARD_ESP32.md |
| `esp32_uart_soak_cable2.csv` | ESP32, 40 soak uploads with the kit defaults and the new cable | BOARD_ESP32.md, "Re-test after a cable change" |
| `esp32_uart_soak_open_a.csv`, `esp32_uart_soak_open_b.csv` | ESP32, 40 soak uploads each: current port open, and DTR and RTS released before the open | BOARD_ESP32.md, "Port open and connect failures" |
| `update_runs_wifi_esp32.csv` | ESP32, 30 update runs over Wi-Fi: 10 from the first Wi-Fi session, 20 from the second Wi-Fi session | BOARD_ESP32.md, "Wi-Fi results" |
| `update_runs_wifi_esp32_first_attempt.csv` | The same, first attempt: 8 runs marked failed by a mistake in the host script, the updates had worked | BOARD_ESP32.md, "Wi-Fi results" |
| `erase_sweep_wifi_esp32.csv` | ESP32, erase asked for over UDP, reset 100, 300 and 500 ms into it | BOARD_ESP32.md, "More Wi-Fi evidence" |
| `erase_sweep_esp32.csv` | ESP32, reset 100, 300 and 500 ms into a slot 1 erase | BOARD_ESP32.md |
| `failure_runs_esp32_case10.csv`, `failure_runs_esp32_case7.csv` | ESP32: case 10 three times, case 7 five times, before slot 0 validation was turned on | BOARD_ESP32.md |
| `powerloss_latency.csv` | 10 runs, `OFF` command to console silence | The power loss tests, POWERLOSS.md |
| `powerloss_runs.csv` | 60 power cuts: 55 by plan, 5 repeats | The power loss tests, POWERLOSS.md |
| `powerloss_stlink_voltage.csv` | Target voltage as reported by the ST-LINK, 5 readings per relay state | POWERLOSS.md |
| `powerloss_first_attempt.csv` | 8 cuts of a stopped first attempt, with a wrong reference file in the test script | POWERLOSS.md, "Results" |

Columns of the update files: run number, target version, ok, version read back, image size in bytes, upload time, MCUboot plus swap time, total time, error text. Times in seconds.
The older files were recovered from the history of the private development repository.
