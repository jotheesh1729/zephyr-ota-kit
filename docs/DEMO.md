# 60 second demo

Shows a good update, then a bad image that recovers on its own.

What the camera sees: the green LED (LD2) and a terminal.

| LED | Meaning |
|---|---|
| Slow blink, once a second | v1.0.0 |
| Fast blink, 5 times a second | v1.1.0 |
| Solid on, not blinking | v1.2.0, the hung image |

## Before recording

```sh
source ~/zephyrproject/.venv/bin/activate
scripts/build.sh 1.0.0
scripts/build.sh 1.1.0
scripts/build.sh 1.2.0 -DCONFIG_APP_HANG=y     # the bad image
(cd ~/zephyrproject && west flash -d "$OLDPWD/build/v1.0.0" --runner openocd)
```

Check that the LED blinks slowly. Put the board and the terminal in the same frame.

## Recording

| Time | Do | Say | Expect on screen |
|---|---|---|---|
| 0:00 | Point at the slow LED | "STM32 running version 1.0. Secure over the air update with MCUboot." | Slow blink |
| 0:05 | Run command 1 | "I upload a signed version 1.1 over UART." | Upload counter, about 8 s |
| 0:14 | Wait | "MCUboot checks the ECDSA signature, swaps the slots, boots it in test mode." | `Swap type: test`, LED goes fast |
| 0:19 | Wait | "The app runs a health check, then confirms itself." | `health check OK, image confirmed`, `RESULT OK` |
| 0:25 | Run command 2 | "Now a bad image. Correctly signed, but it hangs at boot." | Upload counter, about 8 s |
| 0:38 | Point at the LED | "It booted and froze. Nobody is feeding the watchdog." | `simulated hang`, LED solid on |
| 0:48 | Wait, hands off | "After ten seconds the watchdog resets the chip. MCUboot sees an unconfirmed image and swaps the old one back." | `Swap type: revert` |
| 0:54 | Point at the fast LED | "Back on version 1.1, with no one touching the board." | `last reset by WATCHDOG`, `RESULT ROLLED BACK`, LED fast |

Command 1:

```sh
scripts/ota_update.py build/v1.1.0/app/zephyr/zephyr.signed.bin
```

Command 2:

```sh
scripts/ota_update.py build/v1.2.0/app/zephyr/zephyr.signed.bin
```

## Timing budget

Measured values are in `docs/RESULTS.md`. Rough budget for the video:

- Good update: about 18 s (8.4 s upload, 4.5 s swap, 5 s health window).
- Bad image: about 28 s (8.4 s upload, 4.5 s swap, 10 s watchdog, 5 s revert).
- That leaves about 14 s for talking and typing. Have both commands in the shell history.

## If something goes wrong

- Reset to a clean state: `tests/run_tests.py 1-good` runs the baseline reset first and leaves the board on v1.0.0.
- Command 2 exits with a non zero code. That is correct, the update did not stick.
