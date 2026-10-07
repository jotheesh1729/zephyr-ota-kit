# Deviations

Findings of the static analysis that were not fixed, with the reason and the risk.

- Tool: cppcheck 2.13.0 with its MISRA addon, run by `scripts/static_analysis.py`. See [QUALITY.md](QUALITY.md) for what that run can and cannot show.
- Rules are given by number only. The MISRA rule texts are licensed and are not in this repository.
- The numbers refer to MISRA C:2012. Whether a finding is a true violation of the rule as written was judged from the rule number and common knowledge of the rule, not against a licensed copy of the text. Treat the "reason" column with that in mind.
- Line numbers are those after the licence headers were added to the sources (5 lines more than when this file was first written).
- This is not a MISRA compliance claim, and these are not formal deviation records in the sense of MISRA Compliance.

| # | Rule | File and line | What the tool sees | Reason it stays | Risk |
|---|---|---|---|---|---|
| 1 | MISRA 10.3 | `app/src/main.c:37` | `ok = false;` | The analysis runs on preprocessed code, where the C library's `false` has already become the integer `0`. In the source a `bool` gets a `bool` constant | None seen. An effect of the method |
| 2 | MISRA 10.3 | `src/ota_kit.c:74` | `ok = false;` | Same as 1 | None seen |
| 3 | MISRA 10.3 | `src/ota_kit.c:115` | `decided = true;` | Same as 1 | None seen |
| 4 | MISRA 10.1 | `src/ota_kit.c:38` | `.flags = WDT_FLAG_RESET_SOC` | The value is a Zephyr macro built with a bit shift on a signed constant. The expression is inside Zephyr's header | Low. A fixed, small constant. Changing it means not using Zephyr's API constant |
| 5 | MISRA 8.4 | `src/ota_kit.c:121` | `K_THREAD_DEFINE(ota_kit_health, ...)` | The macro defines objects with external linkage and no earlier declaration. That is how Zephyr creates a static thread | Low. The names are prefixed `ota_kit_`. A clash would be a link error |
| 6 | MISRA 8.4 | `src/ota_kit_ble.c:98` | `K_THREAD_DEFINE(ota_kit_ble, ...)` | Same as 5 | Low |
| 7 | MISRA 8.9 | `src/ota_kit_ble.c:18` | `static const struct bt_data ad[]` at file scope, used in one function | `BT_DATA_BYTES` expands to a compound literal. That is a constant initializer only at file scope. Moving it into the function was tried: the build fails with "initializer element is not constant" | Low. The object is `static const` |
| 8 | MISRA 8.9 | `src/ota_kit_ble.c:23` | `static const struct bt_data sd[]` at file scope | Kept next to `ad[]` for the same pattern | Low |
| 9 | MISRA 7.2 | `src/ota_kit_ble.c:20` | `BT_DATA_BYTES(BT_DATA_UUID128_ALL, SMP_BT_SVC_UUID_VAL)` | The UUID bytes are hexadecimal constants without a `u` suffix, inside Zephyr's `SMP_BT_SVC_UUID_VAL` | Low. Each constant is one byte |
| 10 | MISRA 10.4 | `src/ota_kit_ble.c:29` | `bt_le_adv_start(..., ARRAY_SIZE(ad), ..., ARRAY_SIZE(sd))` | Mixed signedness inside Zephyr's `ARRAY_SIZE` and `BT_LE_ADV_CONN_FAST_1` macros | Low. Array sizes of 2 and 1 |
| 11 | cppcheck `constParameterCallback` | `src/ota_kit_ble.c:45` | `conn` could be a pointer to const | `on_disconnected()` is a Zephyr connection callback. Its signature is fixed by `struct bt_conn_cb`. The tool itself notes that it is a callback | None |

What these have in common: 8 of the 11 are inside Zephyr macros or fixed by Zephyr's API (rows 4 to 11), and 3 are an effect of analysing preprocessed code (rows 1 to 3).
No deviation is in code that decides whether an image is confirmed or reverted, apart from the two assignments in rows 2 and 3.

## What was fixed instead

The first run had 35 findings. 26 were fixed in the source, and the fixes added 2 new ones, which leaves 11.

| Rule | Fixed | Fix |
|---|---|---|
| MISRA 17.7 | 11 of 11 | Return values are now checked where there is something to do (LED setup, loading settings), and discarded with an explicit `(void)` and a comment where there is not (feeding the watchdog, sleeping, submitting work) |
| MISRA 12.1 | 4 of 4 | Parentheses added in conditions and build assertions |
| MISRA 15.5 | 3 of 3 | Functions with an early `return` rewritten to one exit |
| MISRA 2.7 | 3 of 3 | Unused parameters of thread entries and callbacks marked with `ARG_UNUSED()` |
| MISRA 10.4 | 3 of 4 | An explicit cast, a matching literal type, and a plain integer in a build assertion |
| cppcheck `knownConditionTrueFalse` | 2 of 2 | The watchdog state is now compiled out when the watchdog is off, instead of being a variable that never changes |

The 2 new findings are rows 1 and 2 above: rewriting two functions to a single exit (rule 15.5) introduced an `ok = false;` in each, which the tool reports under rule 10.3 for the reason given there.

One fix was taken back: moving the advertising data into the function (rule 8.9) broke the BLE build, see row 7.
