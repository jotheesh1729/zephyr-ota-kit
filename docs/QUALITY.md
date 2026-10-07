# Code quality

What was checked in this project's own C code, with which tools, and what the numbers do and do not mean.

**This is not a MISRA compliance claim.** No MISRA compliance process was followed: there is no guideline enforcement plan, no guideline recategorization plan, and no formal deviation process. A free tool was run, its findings were counted, most were fixed, and the rest are explained in [DEVIATIONS.md](DEVIATIONS.md).

## Scope

Checked: the code written for this project.

| Path | Lines, with the 5 line licence header |
|---|---|
| `src/ota_kit.c` | 122 |
| `src/ota_kit_ble.c` | 98 |
| `include/ota_kit/ota_kit.h` | 27 |
| `app/src/main.c` | 77 |
| `samples/minimal/src/main.c` | 22 |

Not checked: Zephyr, MCUboot, the STM32 HAL, the C library. They are more than 99% of the code in the image. Nothing here says anything about their quality.
Not checked either: the Python scripts, the linker script fragment, Kconfig and CMake files.

## Zephyr's own guideline

Zephyr's coding guideline page (`doc/contribute/coding_guidelines/index.rst` in the Zephyr tree used here) says its rules "are based on MISRA-C 2012 and are a subset of MISRA-C". Its table of main rules has 146 entries in that version.
This project did not check its code against that table rule by rule. The static analysis below runs whatever the cppcheck addon implements, which is a different set.

## Static analysis

```sh
scripts/static_analysis.py build/v1.0.0/app build/ble-v1.0.0/app build/native_sim \
  --accepted tests/static/accepted.txt
```

Tool versions:

| Tool | Version |
|---|---|
| cppcheck, with its bundled MISRA addon (`misra.py`) | 2.13.0 |
| Compiler for the board builds | arm-zephyr-eabi-gcc 14.3.0, Zephyr SDK 1.0.1 |
| Compiler for the native_sim build | gcc 13.3.0 |
| Python | 3.12.3 |

How it runs: every C file of this project is preprocessed by the build's own compiler with the build's own flags, and cppcheck analyses the result. Three builds are used, so that each file is seen in the configurations it is built in (UART, BLE, and native_sim without a watchdog).

Why preprocessed code: cppcheck's own preprocessor cannot expand Zephyr's devicetree macros and stops with an error. An earlier attempt reported "0 findings" for exactly that reason. The script now stops if cppcheck fails to parse a file, so that a failed run cannot look like a clean one.

Results:

| | First run | After the fixes |
|---|---|---|
| Findings in this project's files | 35 | 11 |
| of those, MISRA addon | 32 | 10 |
| of those, cppcheck's own checks | 3 | 1 |
| Files with findings | 3 | 3 |
| Accepted and documented in DEVIATIONS.md | 0 | 11 |

By rule, first run to last run: 17.7: 11 to 0. 10.4: 4 to 1. 12.1: 4 to 0. 15.5: 3 to 0. 2.7: 3 to 0. 8.4: 2 to 2. 8.9: 2 to 2. 10.3: 1 to 3. 10.1: 1 to 1. 7.2: 1 to 1. cppcheck `knownConditionTrueFalse`: 2 to 0. cppcheck `constParameterCallback`: 1 to 1.

### Limits of this analysis

- **Rule coverage is whatever the addon implements.** The cppcheck MISRA addon does not check every MISRA C:2012 rule, and it checks no directives. Which rules it covers in this version was not listed. A rule with no finding may simply not be checked.
- **No rule texts.** The addon runs without the licensed rule text file, so findings are rule numbers only.
- **Preprocessed code hides things.** Rules about the preprocessor and about macro definitions cannot be judged on it. Rule 20.13 is switched off in the script, because the compiler's line markers trigger it on every file.
- **Preprocessed code adds things.** A finding on one of our lines can come from the inside of a Zephyr macro used on that line. 8 of the 11 remaining findings come from Zephyr macros or from signatures fixed by Zephyr's API, and the other 3 from `true` and `false` having already been replaced by integers.
- **Three configurations**, not every combination of Kconfig options.
- **cppcheck is not a qualified tool.** No tool qualification was done, and none of its findings or silences was confirmed with a second tool. clang-tidy is not installed on the build host.
- **No data flow or timing analysis**, no stack depth analysis, no unit tests, no coverage measurement. The tests in this project are system tests on the board.

## Compiler warnings

The default Zephyr build of this project had one warning in its own files, a deprecated macro, and now has none.

For a stricter build the kit has an option, `CONFIG_OTA_KIT_STRICT_WARNINGS`. It adds the two extended warning sets that Zephyr defines for its `W=1` and `W=2` build options (`cmake/compiler/gcc/compiler_flags.cmake`: among them `-Wshadow`, `-Wcast-align`, `-Wlogical-op`, `-Wconversion`, `-Wcast-qual`, `-Wbad-function-cast`, `-Wpointer-arith`, `-Wredundant-decls`, `-Wswitch-default`, `-Wpadded`, `-Wvla`) to this project's sources only.

```sh
scripts/build.sh 7.0.0 -DCONFIG_OTA_KIT_STRICT_WARNINGS=y
```

| | Before the fixes | After |
|---|---|---|
| Distinct warnings located in this project's files (UART and BLE builds) | 1 | 0 |
| Warning lines in total, almost all in Zephyr headers included by our files | 1528 | 1526 |

- The one warning was a deprecated Zephyr macro, `FIXED_PARTITION_DEVICE`, now replaced by `PARTITION_DEVICE`.
- The other 1500 or so are reported inside Zephyr's headers, mostly from `-Wconversion` and `-Wpadded`. They are Zephyr's and were not looked at.
- `-Werror` is not used: with these flags Zephyr's own headers would stop the build.
- The option exists because passing Zephyr's `-DW=1` on the command line did not reach the application image in a sysbuild build. A first attempt therefore built without the extra flags and reported a clean result that meant nothing. That was caught by looking for the flags in `compile_commands.json`.
- Zephyr's documentation pages were searched for these options and no page describing `W=` was found. The flags were taken from the two CMake files named above.

## What the fixes changed

The source changes are in `src/ota_kit.c`, `src/ota_kit_ble.c` and `app/src/main.c`. Behaviour was meant to stay the same, with two exceptions that add a console message: a failed LED setup, and a failed load of the Bluetooth settings.
Image size after the changes: application 47812 B (was 47780 B), RAM unchanged.
The UART failure suite was run again on the changed code, see the BLE regression in [RESULTS.md](RESULTS.md).

## Continuous integration

`.github/workflows/ci.yml` runs on every push:

| Job | What it does | Needs |
|---|---|---|
| host-tests | The doctor tests (`tests/doctor`) and the path check (`tests/check_paths.py`) | Python only |
| native-sim-and-static-analysis | Builds `samples/minimal` for `native_sim/native/64` in a fresh west workspace (Zephyr pinned in `west.yml`), then runs `scripts/static_analysis.py` on that build | Zephyr sources, host gcc, cppcheck |

Not in CI:

- **The board build.** It needs the Zephyr SDK and the STM32 HAL, about a gigabyte of downloads for each run. It was judged too heavy for this project's CI and is done by hand.
- **Every hardware test**: the failure suite, the measurements, BLE. They need the board.
- **Static analysis of the BLE file and of the board configurations.** CI only has the native_sim build, so `src/ota_kit_ble.c` and `app/src/main.c` are analysed by hand with the command at the top of this page.
