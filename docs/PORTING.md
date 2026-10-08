# Porting: from your board to the first signed update

This page gives the steps for a new board. The steps are written in the style of Simplified Technical English.
Each step says what the thing is, why you need it, gives one example from this kit, and then gives the action.

The examples come from the two boards that ran on hardware:

| Board | What was done |
|---|---|
| `disco_l475_iot1` (ST B-L475E-IOT01A) | Failure suite and measurements on hardware, UART and Bluetooth LE. Wi-Fi is partial |
| `esp32_devkitc/esp32/procpu` (ESP32 WROOM-32) | Failure suite and measurements over Wi-Fi. UART is partial. See [BOARD_ESP32.md](BOARD_ESP32.md) |
| `nrf52840dk/nrf52840` | Compile only. Never flashed |
| `native_sim` | The minimal sample builds and runs. No MCUboot, no update |

On a third board you will find problems that this page does not know. Each of the two boards had some.

Tested with Zephyr `v4.4.0-13485-g133c2eb7d3cb` and MCUboot `v2.4.0-118`. Other versions were not tried.

## What the kit gives you

| Part | Where |
|---|---|
| SMP server: image upload, image state, reset | selected by `CONFIG_OTA_KIT` |
| Health thread: confirms a test image only if your function returns true | `src/ota_kit.c` |
| Watchdog: armed before `main()`, fed by the health thread | `CONFIG_OTA_KIT_WATCHDOG` |
| Transport: UART, Bluetooth LE, or UART and Wi-Fi | `CONFIG_OTA_KIT_TRANSPORT_*`, `CONFIG_OTA_KIT_WIFI_UDP`, `CONFIG_OTA_KIT_WIFI_DIAL` |
| MCUboot settings for sysbuild | `sysbuild/Kconfig` |
| Snippets that turn it all on | `snippets/ota-kit`, `snippets/ota-kit-ble`, `snippets/ota-kit-wifi`, `snippets/ota-kit-wifi-dial` |

Your application adds one call:

```c
#include <ota_kit/ota_kit.h>

static bool health_ok(void)
{
	return my_sensor_answers() && my_link_is_up();
}

int main(void)
{
	ota_kit_set_health_check(health_ok);
	/* your application */
}
```

If no check is registered, the kit does not confirm the image. MCUboot then reverts the image at the next reset.

## Step 1: make Zephyr find the module

What: a Zephyr module is a folder that Zephyr adds to a build. The kit is one.
Why: the build must find the options, the source files and the snippets of the kit.
Example: `scripts/build.sh` gives the folder on the command line.

Do one of these:

- Add this repository to your west manifest.
- Give the folder at build time: `-DEXTRA_ZEPHYR_MODULES=/abs/path/to/ota-kit`
- Add this line to the `CMakeLists.txt` of your application, before `find_package(Zephyr ...)`:
  `list(APPEND EXTRA_ZEPHYR_MODULES /abs/path/to/ota-kit)`

With sysbuild, use the command line form. Sysbuild itself must load the module too.

## Step 2: check the flash partitions

What: a partition is a named area of the flash in the devicetree. A sector is the smallest area that the flash can erase.
Why: MCUboot needs three partitions, and its swap needs the same sector size in the two slots.
Example: on the ST board the two slots are on different flash chips, with 2 K and 4 K sectors. That did not work until it was corrected.

1. Build an application for your board.
2. Open `build/zephyr/zephyr.dts`.
3. Find these three labels:

   | Label | Purpose |
   |---|---|
   | `boot_partition` | MCUboot |
   | `slot0_partition` | the image that runs. It must be the `zephyr,code-partition` of the application |
   | `slot1_partition` | the new image |

4. Compare the sector sizes of the two slots. They must be equal.
5. Count the sectors. Slot 0 must have the same number of sectors as slot 1, or one more.

The snippet selects the MCUboot mode "swap using move". This mode needs no scratch partition.

Example. The board file of the ST board gives:

```
boot_partition   0x00000   64 K   internal flash, 2 K pages
slot0_partition  0x10000  928 K   internal flash, 2 K pages
slot1_partition  0x00000  864 K   external QSPI flash, 4 K sectors
```

The sector sizes are different, and the sector counts do not agree with the rule. Two corrections were necessary.

Correction 1, sector size. MCUboot can put hardware sectors together into larger logical sectors. Use the larger of the two sizes:

```
SB_CONFIG_OTA_KIT_MCUBOOT_LOGICAL_SECTOR_SIZE=0x1000
```

MCUboot marks this option as experimental.

Correction 2, sector count. Slot 1 is 864 K, which is 216 sectors of 4 K. Slot 0 must then be 217 sectors, which is 868 K:

```dts
&slot0_partition {
	reg = <0x10000 DT_SIZE_K(868)>;
};
```

60 K of the internal flash are then not used. MCUboot and the application must both get this change.

If your two slots are on the same flash, you usually need no correction. The ESP32 needed none.

## Step 3: reset an external flash

Do this step only if slot 1 is on an external flash chip.

What: a reset command tells the flash chip to stop its work.
Why: a reset of the microcontroller does not reset the flash chip. If the chip was erasing, it stays busy, and the next start cannot use it.
Example: on the ST board, MCUboot called `abort()` and the board did nothing for 30 seconds. With the correction the board started in 0.6 seconds.

For the STM32 QSPI driver (`st,stm32-qspi-nor`), add two properties to the flash node:

```dts
&mx25r6435f {
	reset-cmd;
	reset-cmd-wait = <15000>;	/* microseconds */
};
```

- `reset-cmd` makes the driver send the reset commands 0x66 and 0x99 when it starts.
- `reset-cmd-wait` is the recovery time from the flash datasheet, with margin. MX25R6435F rev 1.6, table 13: 12 ms, so 15000 is used.

The kit stops the build if slot 1 is on such a flash and `reset-cmd` is missing.
The kit does not check other flash drivers. Find the reset method of your driver.

## Step 4: watchdog

What: a watchdog is a hardware timer that resets the device when the software stops restarting it.
Why: a new image can hang. Without a reset, MCUboot never gets the chance to revert it.
Example: a test image that hangs in `main()` was reset after 10.1 seconds on the two boards, and MCUboot reverted it.

The kit uses the device behind the devicetree alias `watchdog0`.

1. Make sure that your board has the alias `watchdog0`. Add it if it is missing.
2. Find the longest timeout of your watchdog in the datasheet.
3. Compare the two timeouts of the kit with it:

   | Option | Default | Check |
   |---|---|---|
   | `CONFIG_OTA_KIT_WATCHDOG_TIMEOUT_MS` | 10000 | Not more than the watchdog can do. More than `CONFIG_OTA_KIT_HEALTH_DELAY_S` (5 s), with margin |
   | `SB_CONFIG_OTA_KIT_MCUBOOT_WATCHDOG_TIMEOUT_MS` | 0, which keeps the MCUboot default of 300 s | If your watchdog cannot do 300 s, set a value that it can do |

4. Make sure that the watchdog which MCUboot starts stays active when the application starts.

**WARNING: Do step 4 on the hardware. An image that stops before `main()` is reverted only if this watchdog resets the device.**

Example for step 3. The watchdog of the STM32L4 cannot do more than about 32.7 s. MCUboot asked for 300 s, the driver refused, and MCUboot ran with no watchdog. One line showed it: `E: Watchdog install timeout failed: -22`. With 30000 the line is gone. A swap can take longer than the timeout, because MCUboot restarts the watchdog during the swap.

Example for step 4. On the ESP32 the default watchdog is in timer group 0. The start code of the application resets that timer group, and the watchdog with it. A device with an image that stopped before `main()` stayed stopped. The kit now uses the watchdog of timer group 1 on that board.

To test step 4, build the example application with `-DCONFIG_APP_HANG_EARLY=y`, send it as an update, and do not reset the device. The device must reset without help and start the old version.

The watchdog does not find a hang in the SMP thread, or in threads with a lower priority. This is a result of the design of the feed thread.

## Step 5: transport

What: the transport carries SMP between the host and the device.
Why: the host uploads the image, reads the slot state and resets the device through it.

UART (default):

- Add `chosen { zephyr,uart-mcumgr = &your_uart; };` to the devicetree. It can be the console UART.
- The UART driver must support interrupts.
- There is no authentication. A person on the port can upload, erase slot 1 and reset.

Bluetooth LE (`-S ota-kit-ble`):

- The board needs a `zephyr,bt-hci` controller that works.
- The board needs a `storage_partition`. The kit keeps the bond there.
- The kit sets a fixed address that is made from the chip ID, so the bond stays valid after a reset. This is not a registered address. On the ESP32 the option is off, the chip has its own address.
- The link is encrypted, but pairing does not prove the identity of the host. Read the security part of [TRANSPORTS.md](TRANSPORTS.md).

Wi-Fi, two forms. Select the form that your Wi-Fi driver can do:

- `-S ota-kit-wifi`: for a driver with a full socket interface. The device listens on UDP port 1337. Tested on the ESP32.
- `-S ota-kit-wifi-dial`: for a driver that can only do `send()` and `recv()` on a connected socket, such as eS-WiFi on `disco_l475_iot1`. The device opens a UDP socket to a host address that is fixed at build time. Run `scripts/udp_relay.py` on that host. Status on that board: partial, see [TRANSPORTS.md](TRANSPORTS.md).

For the two forms:

- The board needs a `storage_partition`.
- UART stays active as the console and as a second transport.
- There is no encryption and no authentication. A person on the network can upload, erase slot 1 and reset.
- The network name and the passphrase are stored on the board as plain text. Erase them before you give the board to another person.

## Step 6: put the board settings in the right place

What: MCUboot and the application are two different images. Sysbuild builds the two.
Why: the flash layout, the flash reset and the watchdog alias must be the same in the two images.
Example: the kit has one overlay file for each of its boards, and the snippet gives that file to the two images.

How this repository does it, in `snippets/ota-kit/snippet.yml`:

```yaml
boards:
  /disco_l475_iot1(/.*)?/:
    append:
      EXTRA_DTC_OVERLAY_FILE: boards/disco_l475_iot1.overlay
      SB_EXTRA_CONF_FILE: boards/disco_l475_iot1-sb.conf
```

The board key is compared with the full board target, here `disco_l475_iot1/stm32l475xx`. The slashes make it a regular expression.

For your own board, use the standard Zephyr places in your application:

| What | File in your application |
|---|---|
| Overlay for the application | `boards/<board>.overlay` |
| Overlay for MCUboot | `sysbuild/mcuboot.overlay` |
| Sysbuild options | `sysbuild.conf` |

**WARNING: `sysbuild/mcuboot.overlay` replaces the overlay of MCUboot. Put the lines below in your file, or MCUboot is linked into slot 0.**

```dts
/ {
	chosen {
		zephyr,code-partition = &boot_partition;
	};
};
```

Read the build output of MCUboot. The FLASH region must have the size of your boot partition, not the size of slot 0.

Do not put application options such as `CONFIG_OTA_KIT=y` into a `.conf` file of a snippet. MCUboot gets them too.
The snippets of the kit hold sysbuild options only. `sysbuild/CMakeLists.txt` sets the options of the application.

## Step 7: build, check, flash, first update

What: the first image must be written with a probe or a cable. Each later image can go through the update path.

1. Activate the Python environment and install the SMP client.

   ```sh
   source ~/zephyrproject/.venv/bin/activate
   pip install smpclient
   ```

2. Make the signing key one time.

   **WARNING: Do not put the private key in git.**

   ```sh
   imgtool keygen -k keys/ota_signing.pem -t ecdsa-p256
   ```

3. Build version 1.0.0 of your application.

   ```sh
   west build -b <board> --sysbuild -S ota-kit -d build/v1.0.0 <app> -- \
     -DEXTRA_ZEPHYR_MODULES=/abs/path/to/ota-kit \
     -DSB_CONFIG_BOOT_SIGNATURE_KEY_FILE=\"/abs/path/to/ota-kit/keys/ota_signing.pem\"
   ```

4. Change the `VERSION` file of your application to 1.1.0. Build again into `build/v1.1.0`.
5. Check the two builds with the doctor.

   ```sh
   scripts/ota_doctor.py build/v1.0.0
   scripts/ota_doctor.py build/v1.0.0 --slot1-erase-size 4096   # erase size from your flash datasheet
   ```

   The doctor reports the mistakes from steps 2 to 6 that it knows. On a new board, some results are `UNKNOWN`. A report with no `FAIL` does not prove that the board is safe. See [DOCTOR.md](DOCTOR.md).

6. Flash version 1.0.0.

   ```sh
   west flash -d build/v1.0.0
   ```

7. Send version 1.1.0.

   ```sh
   scripts/ota_update.py build/v1.1.0/<app>/zephyr/zephyr.signed.bin --port /dev/ttyACM0
   ```

On the ST board, `scripts/build.sh 1.0.0` and `scripts/build.sh 1.1.0` do steps 3 and 4, and the flash command needs `--runner openocd`.

A good first update prints these lines:

```
I: Image index: 0, Swap type: test          <- MCUboot accepted the signature and swaps
I: Image version: v1.1.0
OTA app v1.1.0, ... TEST boot, not confirmed yet
health check OK, image confirmed            <- printed by the kit after your function returned true
RESULT OK: running v1.1.0, ...
```

`scripts/ota_update.py` looks for these console lines: `Starting bootloader`, `Jumping to the first image slot`, `image confirmed`, `health check FAILED` and `last reset by WATCHDOG`. The example application prints the last one. If your application does not print it, a test for a hang cannot see the reset.

Commands of this step that were run: `imgtool keygen`, `scripts/build.sh`, `scripts/ota_doctor.py`, `west flash` and `scripts/ota_update.py`, on the two boards. Not run: the `west build` line with `<board>` and `<app>` for a third board.

## Step 8: when it does not work

Each row was seen on `disco_l475_iot1`, or on the ESP32 where the row says so. The first row comes from the MCUboot source.

| Symptom | Cause | Fix |
|---|---|---|
| MCUboot warns `Cannot upgrade: not a compatible amount of sectors` or `not same sector layout` | Slot sizes or sector sizes break the swap using move rules | Step 2 |
| MCUboot build shows a FLASH region the size of slot 0 | Your `sysbuild/mcuboot.overlay` dropped the code partition choice | Step 6 |
| `E: Watchdog install timeout failed: -22` | MCUboot's watchdog timeout is beyond the hardware | Step 4 |
| After a reset: `I: Starting bootloader`, `abort()`, then silence | External flash still busy from an erase | Step 3 |
| Board resets about 10 s into a slot erase | Something starves the health thread. The kit runs it above the SMP thread for this reason | Keep long work out of threads above the health thread |
| Kconfig stops with a warning about `UART_INTERRUPT_DRIVEN` | The UART driver has no interrupt support | `CONFIG_OTA_KIT_TRANSPORT_CUSTOM`, or another UART |
| BLE works until the first reset, then the host cannot reconnect | The address changed, so the stored bond is useless | Keep `CONFIG_OTA_KIT_BLE_DEVICE_ADDR_FROM_CHIP_ID=y` |
| `smp_udp: recvfrom error ...: 95` in a loop | The sockets of the network driver refuse `recvfrom()` and `sendto()` with an address | Use `-S ota-kit-wifi-dial`, see [TRANSPORTS.md](TRANSPORTS.md) |
| ESP32: `E (flash_init): Failed to init flash chip: 1`, then `abort()`, before the application prints a line | A fault in the early flash code of the Espressif HAL, which depends on the link layout | Apply the patch, see [BOARD_ESP32.md](BOARD_ESP32.md) |
| An image stops before `main()` and the device does not reset | The watchdog of MCUboot is off, or it does not stay active when the application starts | Step 4 |
| ESP32: an image written to slot 0 with a wrong signature starts | The ESP32 configuration of MCUboot turns off the check of slot 0. The kit turns it on | Use the `ota-kit` snippet, and run the doctor, rule SIG-02 |
| Upload refused with `INVALID_IMAGE_HEADER_MAGIC` | You uploaded `zephyr.bin` | Upload `zephyr.signed.bin` |
| A signed image uploads, then `E: Image in the secondary slot is not valid!` | Wrong key, corrupt image, or the image is larger than MCUboot can swap although it built | Run the doctor, rule SIZE-01 |

## Step 9: the tests on another board

`tests/run_tests.py` and `tests/measure.py` know two boards, selected with the `BOARD` variable. For a third board, these parts must change:

- The baseline flashes with OpenOCD for the ST board, and with `esptool` for the ESP32.
- The test images use the options of the example application in `app/` (`CONFIG_APP_HANG`, `CONFIG_APP_HEALTH_FORCE_FAIL`, `CONFIG_APP_PAD_BYTES`).
- The console lines they look for are the ones the example application prints.

To reuse them, replace the flash commands in `baseline()` and build your test images from an application that prints the same lines.

## Options at a glance

Application image:

| Option | Default | Meaning |
|---|---|---|
| `CONFIG_OTA_KIT` | n | The kit. Needs `CONFIG_BOOTLOADER_MCUBOOT` |
| `CONFIG_OTA_KIT_TRANSPORT_UART` / `_BLE` / `_CUSTOM` | UART | SMP transport |
| `CONFIG_OTA_KIT_HEALTH_DELAY_S` | 5 | Seconds a test image runs before the health check |
| `CONFIG_OTA_KIT_WATCHDOG` | y if alias `watchdog0` exists | Arm and feed the watchdog |
| `CONFIG_OTA_KIT_WATCHDOG_TIMEOUT_MS` | 10000 | Limited to 1000..32000 on STM32L4 |
| `CONFIG_OTA_KIT_WATCHDOG_FEED_MS` | 1000 | Feed period |
| `CONFIG_OTA_KIT_HEALTH_STACK_SIZE` | 1024 | Health thread stack |
| `CONFIG_OTA_KIT_REQUIRE_EXT_FLASH_RESET` | y | Build check for `reset-cmd`, STM32 QSPI only |
| `CONFIG_OTA_KIT_BLE_DEVICE_ADDR_FROM_CHIP_ID` | y with BLE | Fixed address so bonds survive resets |
| `CONFIG_OTA_KIT_SIZE_GUARD` | y with swap using move, Cortex-M only | Build fails if the image is larger than MCUboot can swap |
| `CONFIG_OTA_KIT_WIFI_UDP` | n | Adds SMP over UDP on Wi-Fi to the selected transport |
| `CONFIG_OTA_KIT_WIFI_DIAL` | n | Adds SMP over a connected UDP socket that the device opens to `CONFIG_OTA_KIT_WIFI_DIAL_HOST` |
| `CONFIG_OTA_KIT_WIFI_LAYOUT_PAD_WORDS` | 1 with Wi-Fi | Workaround for the ESP32 early start fault, see [BOARD_ESP32.md](BOARD_ESP32.md) |
| `CONFIG_OTA_KIT_SWAP_SECTOR_SIZE` | 0x0, from the devicetree | Sector size for the size guard, set by sysbuild with logical sectors |

Sysbuild:

| Option | Default | Meaning |
|---|---|---|
| `SB_CONFIG_OTA_KIT` | n, set by the `ota-kit` snippet | Turn the kit on in the application image |
| `SB_CONFIG_OTA_KIT_TRANSPORT_BLE` | n, set by the `ota-kit-ble` snippet | BLE instead of UART |
| `SB_CONFIG_OTA_KIT_WIFI_UDP` | n, set by the `ota-kit-wifi` snippet | SMP over UDP on Wi-Fi, in addition |
| `SB_CONFIG_OTA_KIT_WIFI_DIAL` | n, set by the `ota-kit-wifi-dial` snippet | SMP over a connected UDP socket, in addition |
| `SB_CONFIG_OTA_KIT_MCUBOOT_CONSOLE_LOG` | n, set for the ESP32 | Turns on the console and the log of MCUboot |
| `SB_CONFIG_OTA_KIT_DOWNGRADE_PREVENTION` | n, set by the `ota-kit` snippet | MCUboot refuses an image with a lower version, at boot |
| `SB_CONFIG_OTA_KIT_MCUBOOT_WATCHDOG_TIMEOUT_MS` | 0 | MCUboot watchdog timeout, 0 keeps MCUboot's default |
| `SB_CONFIG_OTA_KIT_MCUBOOT_LOGICAL_SECTOR_SIZE` | 0x0 | Logical sectors for slots with different erase sizes |
| `SB_CONFIG_OTA_KIT_MCUBOOT_MAX_IMG_SECTORS` | 256 | Sector count limit, used with logical sectors |

The `ota-kit` snippet also sets `SB_CONFIG_BOOTLOADER_MCUBOOT`, swap using move, and ECDSA P256 signatures. The kit sets `CONFIG_BOOT_VALIDATE_SLOT0=y` in MCUboot.

Without sysbuild, set `CONFIG_BOOTLOADER_MCUBOOT=y` and `CONFIG_OTA_KIT=y` in your `prj.conf`, as `samples/minimal` does, and build MCUboot yourself.
