# Findings for upstream

Five findings and one question that concern Zephyr, MCUboot or the Espressif HAL rather than this project.
Two are from the ST B-L475E-IOT01A (`disco_l475_iot1`), three from an ESP32 dev board (`esp32_devkitc`).
Written so that they can be reported or discussed upstream. **This is a draft. Nothing here has been sent.**

Versions: Zephyr `133c2eb7d3cb` (4.4 development tree), MCUboot `7ad67106` (2026-07-29), hal_espressif `5e3b702250`, Zephyr SDK 1.0.1.

About novelty: the issue trackers were searched, a handful of queries per finding, on the dates given in each section.
**No claim is made that any of this is new.** A search that finds nothing identical does not show that nothing exists.
"Read" means the page or its description was read. "Title only" means only the search result title was seen.

| # | Finding | What exists upstream | What was measured here |
|---|---|---|---|
| 1 | MCUboot's default watchdog timeout, 300 s, is above what the STM32L4 IWDG can do, so MCUboot runs with no watchdog | No report of this case found. The option came with MCUboot 2.2.0 | `Watchdog install timeout failed: -22` at every boot with the default. With 30 s the watchdog runs and a 56 s swap still completes |
| 2 | A reset during a QSPI flash erase makes MCUboot `abort()`, the board is dead until its watchdog fires | Related reports for other drivers and for the `reset-cmd` property. None for this board or this combination | 30.6 s dead without `reset-cmd`, 0.6 s with it |
| 3 | MCUboot's ESP32 SoC configuration turns off the check of slot 0 | The setting dates from MCUboot pull request #1582. No report found | A corrupted image written to slot 0 was started. With the option on it was refused. Cost 96 B |
| 4 | ESP32: the early flash init can run garbage after the flash cache is switched back on | **Already reported**: Zephyr issue #120719, open, with a two line fix proposed. Not merged on 2026-10-07 | One build aborted before `main()`. With the two lines the same layout booted. Sent as an update, the image left the board dead until a reset |
| 5 | ESP32: a watchdog that MCUboot starts on timer group 0 does not survive the jump into the application | No report found | No reset with 30 s or 5 s on timer group 0. Reset after 30.0 s on timer group 1 |
| 6 | Question: with slot 0 one sector larger than slot 1, should the application's size limit include that sector | Related reports and fixes, listed in the section | The linker allowed 3946 B more than MCUboot can swap |

---

## 1. MCUboot's default watchdog timeout is beyond what the STM32L4 IWDG can do

### Symptom

One line at every boot, and nothing else:

```
E: Watchdog install timeout failed: -22
```

MCUboot then runs, swaps and boots the application normally. It has no watchdog.

### Cause

- MCUboot's Zephyr port installs a watchdog timeout at boot (`CONFIG_BOOT_WATCHDOG_INSTALL_TIMEOUT_AT_BOOT`, default y). `CONFIG_BOOT_WATCHDOG_TIMEOUT_MS` defaults to 300000.
- The STM32 IWDG driver (`drivers/watchdog/wdt_iwdg_stm32.c`) accepts at most prescaler 256 x (reload 0xFFF + 1) / LSI 32000 Hz = 32.768 s on STM32L4, and returns `-EINVAL` above that.
- In `boot/zephyr/watchdog.c`, when `wdt_install_timeout()` fails, `wdt_setup()` is not called. So the watchdog is not started at all.
- MCUboot ships a board file for this board, `boot/zephyr/boards/disco_l475_iot1_stm32l475xx.conf`, that sets `CONFIG_WATCHDOG=y`. So the stock configuration for this board hits it.

### Evidence and numbers

| | 300000 ms (default) | 30000 ms |
|---|---|---|
| Log line at boot | `Watchdog install timeout failed: -22` | none |
| Watchdog during MCUboot | not running | running |
| A 56 s swap of an 840 K image | completes | completes, the watchdog is fed along the way |
| Board dead after MCUboot `abort()` (finding 2) | would stay dead | resets after 30 s |

The first and second row were seen in every boot before and after the change. The last row, left column, was not run: it follows from the watchdog not being started.

### Fix used here

`CONFIG_BOOT_WATCHDOG_TIMEOUT_MS=30000` for this board, through `SB_CONFIG_OTA_KIT_MCUBOOT_WATCHDOG_TIMEOUT_MS`.

### Suggested upstream change

One or more of these, for the maintainers to judge:

1. In MCUboot's board file for `disco_l475_iot1` (and other STM32 boards with `CONFIG_WATCHDOG=y`), set a timeout the IWDG can do.
2. In `watchdog.c`, when the requested timeout is refused, say what that means ("MCUboot runs without a watchdog") rather than only the error code. Or try the largest timeout the driver accepts.
3. A build time check is not possible in general, since the driver decides at run time.

### Existing reports

- No report of this exact case was found.
- MCUboot release notes, version 2.2.0 (read): "Watchdog support in Zephyr has been reworked and fixed to allow installing a timeout (with a configurable value) before starting it." This is the change that introduced the option.
- MCUboot PR #2879, "boot: zephyr: Fix watchdog feed without an installed timeout" (title only): https://github.com/mcu-tools/mcuboot/pull/2879
- Zephyr issues about the STM32 IWDG driver and timeouts, different problems (titles only): https://github.com/zephyrproject-rtos/zephyr/issues/45112 , https://github.com/zephyrproject-rtos/zephyr/issues/71333 , https://github.com/zephyrproject-rtos/zephyr/issues/53240

---

## 2. A reset during a QSPI flash erase leaves MCUboot unable to boot for as long as its watchdog takes

### Symptom

After a reset of the MCU while the external flash is erasing:

```
I: Starting bootloader
abort()
(silence)
```

With MCUboot's watchdog running (30 s, see finding 1) the board resets and then boots normally. Without it the board stays dead until someone resets it.

### Cause

- Slot 1 is on an MX25R6435F behind the STM32 QUADSPI peripheral, driver `drivers/flash/flash_stm32_qspi.c`.
- A reset of the MCU (watchdog, reset pin, software) does not reset the flash chip. If it was in the middle of an erase it stays busy.
- The driver's init does not wait for the flash to become ready before its first command, and does not reset it unless the devicetree asks for that. Init fails, the flash device is not ready, MCUboot cannot open its flash areas and calls `abort()`.
- The driver does have a remedy: the devicetree properties `reset-cmd` and `reset-cmd-wait` make it send the reset commands (0x66, 0x99) at init. The board file `boards/st/disco_l475_iot1/disco_l475_iot1.dts` does not set them, although it places `slot1_partition` on that flash.

How it was first hit: a slot erase requested over MCUmgr takes about 15 s on this flash. A watchdog reset arrived 9.4 s into it.

### Evidence and numbers

Test: fill slot 1, start a whole slot erase, hardware reset 3 s into it, time until the application banner.

| | Without `reset-cmd` | With `reset-cmd`, wait 15 ms |
|---|---|---|
| Time from reset to application | 30.6 s (1 run) | 0.6 s (in every run since, more than 5) |
| MCUboot `abort()` | yes | no |

The 30 s is MCUboot's watchdog timeout, not a property of the flash.
Recovery time of the flash from the datasheet (MX25R6435F rev 1.6, table 13): 12 ms after a reset command during an erase.

### Fix used here

In an overlay applied to both MCUboot and the application:

```dts
&mx25r6435f {
	reset-cmd;
	reset-cmd-wait = <15000>;
};
```

### Suggested upstream change

1. Set `reset-cmd` and a suitable `reset-cmd-wait` in the `disco_l475_iot1` board file, since the board file itself puts an MCUboot slot on that flash.
2. Consider making the driver's init wait for the write in progress bit to clear, with a timeout, before its first command. That would cover boards that cannot send a reset command.
3. The default `reset-cmd-wait` is 10 microseconds. For this flash a reset during an erase needs 12 ms. A note in the binding that the value depends on what the flash was doing would help.

### Existing reports

- Zephyr issue #51713, "drivers: flash: spi_nor: init fails when flash is busy" (title and search summary only): https://github.com/zephyrproject-rtos/zephyr/issues/51713 . The same class of problem, for the generic SPI NOR driver. Whether and how it was fixed there was not checked.
- Zephyr issue #76896, "st,stm32-qspi-nor driver resets flash chip by default and returns incorrect JEDEC ID" (read, closed): https://github.com/zephyrproject-rtos/zephyr/issues/76896 . About the same property. Its fix made the reset happen only when `reset-cmd` is set. So before that fix this driver reset the flash on every init, and this problem would not have shown.
- Zephyr issue #37501, "mcuboot: Application fails to access QSPI flash after image swap" (title only): https://github.com/zephyrproject-rtos/zephyr/issues/37501
- No report was found for this board, or for the combination "reset during erase, then MCUboot aborts".

---

## 3. MCUboot's ESP32 configuration turns off the check of slot 0

Seen in the first ESP32 trial on an `esp32_devkitc`. This is a default that was chosen upstream, **not claimed to be a bug and not claimed to be new**.

### Symptom

MCUboot built by sysbuild for `esp32_devkitc/esp32/procpu` starts an image from slot 0 without verifying it.
An image with 4 flipped bytes, written straight to slot 0 with `esptool`, was started:

```
I: Image index: 0, Swap type: none
I: Image version: v2.0.4
I: Jumping to the first image slot
```

An update that arrives through slot 1 is still verified. The same damaged image, uploaded over SMP, was rejected.

### Cause

`boot/zephyr/socs/esp32_procpu.conf` in MCUboot sets `CONFIG_BOOT_VALIDATE_SLOT0=n`. The Kconfig default is `y`.
The same line is in all nine ESP32 SoC files in that folder (`esp32c2`, `esp32c3`, `esp32c5_hpcore`, `esp32c6_hpcore`, `esp32h2`, `esp32p4_hpcore`, `esp32s2`, `esp32s3_procpu`, `esp32_procpu`).
The same file also selects `CONFIG_BOOT_SIGNATURE_TYPE_NONE=y` and `CONFIG_BOOT_UPGRADE_ONLY=y`.

History, from `git log` in MCUboot `7ad67106`:

- The line first appears in commit `67693442`, "boot: zephyr: esp32: zephyr port", pull request #1582, merged 2023-04-27: https://github.com/mcu-tools/mcuboot/pull/1582
- Commit `018dc01d`, "boot/zephyr: use socs conf", pull request #1956, 2024-05-07, moved the board files into `socs/`: https://github.com/mcu-tools/mcuboot/pull/1956

The description and the 17 comments of #1582 were searched for "VALIDATE" and "signature": no match. **The reason for the setting is not known to this project.**

### Evidence and numbers

- With the option off: log above. With `CONFIG_BOOT_VALIDATE_SLOT0=y`: `E: Image in the primary slot is not valid!`, `E: Unable to find bootable image`.
- Cost of turning it on in this build: 96 B of MCUboot (54000 to 54096 B). Boot time was not measured.
- Details: [BOARD_ESP32.md](BOARD_ESP32.md), "Slot 0 validation".

### Fix used here

The kit's sysbuild hook sets `CONFIG_BOOT_VALIDATE_SLOT0=y` for MCUboot. The doctor has a rule for it, SIG-02.

### Question for the maintainers

Is `CONFIG_BOOT_VALIDATE_SLOT0=n` for the ESP32 targets meant for the default configuration without a signature only?
A user who selects a signature type in sysbuild still gets a bootloader that does not check slot 0, and nothing in the build output says so.

### Existing reports

Searched on 2026-10-06 with the GitHub issue search, issues and pull requests, in `mcu-tools/mcuboot` and `zephyrproject-rtos/zephyr`:
"BOOT_VALIDATE_SLOT0 esp32", "VALIDATE_SLOT0 espressif", "BOOT_VALIDATE_SLOT0 espressif", "esp32 zephyr mcuboot signature primary slot validation". **No report found.**
That is a search result, not proof that nobody has raised it. Mailing lists, Discord and the Espressif forum were not searched.

- MCUboot issue #1308, "MCUboot boot-up time" (start of the text read, closed): the one issue the search for "BOOT_VALIDATE_SLOT0" returned besides a 2019 rename. It is about boot time with the option off, not about ESP32. https://github.com/mcu-tools/mcuboot/issues/1308

## 4. ESP32: the early flash init can run garbage after the flash cache is switched back on

Seen on an `esp32_devkitc` (ESP32-D0WD revision v1.0) on 2026-10-07. **Already reported upstream by someone else. Nothing here is new.**

### What exists upstream

- Zephyr issue #120719, "hal_espressif: ESP32 no-OS flash guard re-enables the cache without invalidating it", opened 2026-09-29 (read): https://github.com/zephyrproject-rtos/zephyr/issues/120719
- State on 2026-10-07: open, no comments, no pull request linked in its timeline. The `zephyr` branch of `hal_espressif` does not have the proposed lines in `components/spi_flash/spi_flash_os_func_noos.c`.
- The report describes a silent hang right after `I (spi_flash): flash io: dio`, on a custom ESP32-D0WD board, depending on the link layout. It says it had not been run on a DevKitC.
- Other issues with the same error text, different problems, descriptions read: Zephyr #83743 (https://github.com/zephyrproject-rtos/zephyr/issues/83743), esp-idf #13380 (https://github.com/espressif/esp-idf/issues/13380).
- Searched with the GitHub issue search for "Failed to init flash chip" and the function names in `zephyrproject-rtos/zephyr`, `zephyrproject-rtos/hal_espressif` and `espressif/esp-idf`. Whether esp-idf's own copy of the code has the same gap was not checked.

### What was measured here

- One build of the kit's Wi-Fi image aborted before `main()` on every boot: `E (flash_init): Failed to init flash chip: 1`, then `abort()`. A wrong return value instead of the hang of the report, at the same place.
- In the failing image the call to `esp_flash_init_main()` returns to 0x400dfff6, 10 bytes before a 64 K page boundary of the flash mapping. In nine booting images it does not. One failing sample.
- The report's fix, `Cache_Flush(0); Cache_Flush(1);` in the guard's `end()`, applied to the workspace for one build: the same layout booted. Without it, it aborted. One layout, one board, one boot each.
- A consequence the report does not mention: sent as an update, the image halted the board until an outside reset, 3 of 3 runs. Zephyr's `abort()` halts, and nothing resets the chip before the application arms its watchdog. See finding 5.

### What this project does

It carries the two lines as an optional `west patch` (`zephyr/patches.yml`), and one extra data word that moved the layout of its own image. The second is a workaround and is marked fragile.
Details: [BOARD_ESP32.md](BOARD_ESP32.md), "Early boot abort that depends on the link layout" and "Carrying the upstream fix".

---

## 5. ESP32: a watchdog started by MCUboot on timer group 0 does not survive the jump into the application

Seen on the same board on 2026-10-07.

### What exists upstream

No report was found. Searched on 2026-10-07 with the GitHub issue search in `zephyrproject-rtos/zephyr`, `mcu-tools/mcuboot` and `espressif/esp-idf` for combinations of "esp32", "mcuboot", "watchdog", "timer group", "esp_timer_early_init" and "timg_ll_reset_register": no result. Five queries, nothing else was searched.

### Read from the source

- The board's `watchdog0` alias is `wdt0`, the watchdog of timer group 0.
- MCUboot with `CONFIG_WATCHDOG=y` installs its timeout on that alias and starts it. Nothing in the jump code stops it.
- The application's start code calls `esp_timer_early_init()` before anything else of note. With `CONFIG_ESP_TIMER_IMPL_TG0_LAC=y` that function resets the registers of its timer group (`timg_ll_reset_register()` in `esp_timer_impl_lac.c`).

Inferred, not read: that this group is timer group 0 and that the reset is what stops the watchdog.

### What was measured here

Image that aborts before `main()` in slot 0, MCUboot rebuilt for each row:

| MCUboot watchdog | Result |
|---|---|
| Timer group 0, 30 s | no reset in 92 s |
| Timer group 0, 5 s | no reset in 39 s |
| Timer group 1, 30 s | reset after 30.0 s, `rst:0x8 (TG1WDT_SYS_RESET)`, twice in a row |

With timer group 1 in MCUboot and in the application: the aborting image as an update was reverted without help in 2 of 2 runs, and an image that spins in a `PRE_KERNEL_1` init function in 1 of 1.

### Fix used here

The kit makes `wdt1` the `watchdog0` alias on this board, for both images. Details: [BOARD_ESP32.md](BOARD_ESP32.md), "Early hang recovery".

### Question for the maintainers

Is a watchdog handed over from MCUboot to the application meant to work on the ESP32 with the default alias? If so, the early timer init takes it away.

---

## 6. Open question: with slot 0 one sector larger than slot 1, should the application's size limit include that sector?

This one is a question for the maintainers, not a bug report. The numbers are measured. Whether the behaviour is intended, and whose job the limit is, is not something this project can decide.

### Symptom

An image that builds, signs, uploads, and is then refused at boot with the same message as a bad signature:

```
I: Image index: 0, Swap type: test
E: Image in the secondary slot is not valid!
```

The old image keeps running. Nothing is lost except the upload, 140 s here.

### Cause

- MCUboot `design.md`, swap using move: the largest image is `(N - 1) x sector size - trailer`, with N the number of sectors in the primary slot. The image and its trailer must also fit the secondary slot.
- The application's link size comes from `CONFIG_ROM_END_OFFSET`, which MCUboot's sysbuild code works out (`boot/zephyr/CMakeLists.txt`, `mcuboot_image_footer_size`) and Zephyr subtracts from the size of slot 0.
- That code adds one sector for the swap only `if(${slot0_size} EQUAL ${slot1_size})`, and only when the erase sizes of both slots are known from the devicetree (MCUboot commit `2fe443de`, "boot: zephyr: cmake: Add swap sector overhead ... when it is not set in dts already", 2026-07-06).
- This board has slot 0 one sector larger than slot 1, the layout `design.md` calls the most efficient. As far as the code was understood, it then treats the spare sector as already accounted for and subtracts nothing, while the link size is still taken from the larger slot 0. If that reading is right, the application may grow into the spare sector. **This reading of the CMake code was not confirmed by anyone who knows it.** It is possible that a board with this layout is expected to set something else, for example in the devicetree, and that this project's setup is what is wrong.

### Evidence and numbers

Slot 0: 868 K = 217 sectors of 4 K. Slot 1: 864 K = 216 sectors. Trailer 8192 B.

| | Value |
|---|---|
| MCUboot's limit: min((217 - 1) x 4096, 884736) - 8192 | 876544 B |
| What the linker allows (FLASH region, incl. header) | 880490 B |
| Gap | 3946 B |
| Image of 879091 B, inside the gap | builds, uploads, **refused by MCUboot** |
| Image of 876527 B, 17 B under the limit | builds, uploads, swaps in 57 s, confirms |

A second observation, **not investigated**: in a build for `nrf52840dk/nrf52840` with this same MCUboot revision, both slots are 483328 B and on one flash, yet `CONFIG_ROM_END_OFFSET` is 0x2096, which is the trailer plus the TLV estimate without an extra sector. So the sector added by commit `2fe443de` does not show in that build either. That board was never flashed here, so whether an image in that gap fails there is not known.

### Fix used here

A linker assert in this project's module (`linker/size_guard.ld`) with the limit
`min((slot 0 sectors - 1) x sector, slot 1 size) - CONFIG_ROM_END_OFFSET - margin`.

### Questions for the maintainers

1. With slot 0 exactly one sector larger than slot 1, is the application expected to be limited to `min(slot0_size - erase_size, slot1_size) - trailer`? If so, where is that limit meant to come from: MCUboot's sysbuild code, the board's devicetree, or the user?
2. Is the commit named above meant to cover only equal slots, with the larger slot 0 case left to the board on purpose?
3. In the nRF build described above the extra sector does not appear although both slots are equal. Is that expected in that configuration, or did this project's build miss a precondition?
4. Independent of the answers: would a distinct log message for "image too large to swap" be welcome? Today it reads like a signature failure.

No change is proposed until those are answered.

### Existing reports

This area has known reports and recent fixes, listed here. **Nothing about it is claimed to be new.** Whether the case above is a gap, a known limitation, or a mistake in this project's setup is the open question.

- MCUboot release notes (read): version 2.2.0 "Fixed wrong maximum application size calculation when operating in swap using move mode". Version 2.5.0 "Fixed the trailer size that sysbuild reserves at the end of the application for swap-move and swap-offset" and "Swap-offset could build an application too large to swap". https://docs.mcuboot.com/release-notes.html
- Zephyr issue #111595, "mgmt: mcumgr: grp: img: Sysbuild image overhead too small" (read, open, opened 2026-06-18): https://github.com/zephyrproject-rtos/zephyr/issues/111595 . It says MCUmgr's overhead value is one sector too small. Closely related: the same sector, on the upload check side.
- Zephyr issue #79147, "mcuboot/mcumgr: board not upgradable after 'Not enough free space to run swap upgrade' with slot1 big image" (read, closed): https://github.com/zephyrproject-rtos/zephyr/issues/79147 . A worse outcome of an oversized image than seen here.
- MCUboot issue #1845, "Imgtool trailer size check incorrect for swap-using-move" (read, closed): https://github.com/mcu-tools/mcuboot/issues/1845
- Zephyr discussion #73279, "How to set the values of CONFIG_ROM_END_OFFSET and CONFIG_MCUBOOT_UPDATE_FOOTER_SIZE?" (title only): https://github.com/zephyrproject-rtos/zephyr/discussions/73279

## Draft posts

**Drafts. Not sent.** Two posts, because two different groups of people would read them.

For the Zephyr Discord or GitHub Discussions, STM32 and MCUboot:

> **Two findings and a question about MCUboot on disco_l475_iot1 (slot 1 on the QSPI flash)**
>
> I built a small OTA demo on a B-L475E-IOT01A with swap using move and slot 1 on the external MX25R6435F, and tested the failure cases on the board. Three things looked like they belong upstream rather than in my project:
>
> 1. **MCUboot runs without a watchdog on this board.** `CONFIG_BOOT_WATCHDOG_TIMEOUT_MS` defaults to 300000, the STM32L4 IWDG tops out at about 32.7 s, `wdt_install_timeout()` returns -22 and the watchdog is never started. The only sign is one log line. With 30000 it works, and a 56 s swap completes because MCUboot feeds it.
>
> 2. **A reset during a QSPI erase makes MCUboot `abort()`.** The MCU reset does not reset the flash, the STM32 QSPI driver's init fails while the chip is busy, and MCUboot aborts. Adding `reset-cmd` and `reset-cmd-wait` to the flash node takes the boot from 30.6 s to 0.6 s.
>
> 3. **A question about the size limit with swap using move.** My slot 0 is one sector larger than slot 1, as design.md describes. The linker allowed an application of 880490 B, while (N-1) x sector - trailer gives 876544 B. Is the larger slot 0 expected to be reflected in the application's size limit?
>
> Versions: Zephyr 133c2eb7d3cb, MCUboot 7ad67106. Details, logs and numbers: `docs/UPSTREAM.md` in REPLACE_WITH_REPOSITORY_URL.
>
> Happy to send patches for the board file (watchdog timeout, `reset-cmd`) if that is the right fix. The third one is only a question.

As a comment on Zephyr issue #120719, and a question next to it, ESP32:

> A data point from an ESP32-DevKitC (ESP32-D0WD rev v1.0), Zephyr 133c2eb7d3cb, hal_espressif 5e3b702250, application started by MCUboot.
> One build of mine failed on every boot with `E (flash_init): Failed to init flash chip: 1` and `abort()` right after `flash io: dio`. In that image the call to `esp_flash_init_main()` returns to 0x400dfff6, 10 bytes before a 64 K boundary. With the two `Cache_Flush` lines from this issue the same layout boots. One layout, one board.
>
> Two related things I measured:
>
> - Sent as an MCUboot test update, that image left the board halted until an outside reset, because `abort()` halts and no watchdog was running yet.
> - A watchdog that MCUboot starts on `wdt0` did not help: no reset with 30 s or 5 s. On `wdt1` the reset came after 30 s. From the source it looks like `esp_timer_early_init()` resets timer group 0 in the application's start code. Is a watchdog handed over from MCUboot expected to work with the default alias?
> - Separately: MCUboot's `socs/esp32*.conf` set `CONFIG_BOOT_VALIDATE_SLOT0=n`. With a signature type selected in sysbuild, a corrupted image written to slot 0 still booted. Is that setting meant for the unsigned default only?
>
> Logs and numbers: `docs/BOARD_ESP32.md` and `docs/UPSTREAM.md` in REPLACE_WITH_REPOSITORY_URL.
