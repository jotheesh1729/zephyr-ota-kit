# Related work

Existing tools for firmware update on MCUboot and Zephyr class devices, and where this project sits next to them.

## How to read this page

- None of these tools was installed, run, or tested against this board.
- Each "verified" statement was checked on 2026-10-05 by reading the linked page. The reading was done through an automated page fetch that returns extracts, not by a person reading the full page. Treat "verified" as "the linked page said this on that date".
- Anything marked **not verified** came from a search result summary, or is an inference, and was not confirmed on a page.
- Pricing, licensing, current availability and supported board lists were not checked for any of them.

## Short version

This project is not a replacement for any of them.
It is a small, measured reference: one board, the device side update path, and a test suite that injects failures and records what the bootloader does.
It has no fleet management, no cloud, no phone app and no web page.

## Tools that talk to the SMP server directly

These speak SMP (MCUmgr), the protocol this project uses. They would replace `scripts/ota_update.py`, not the firmware.

### nRF Connect Device Manager

Source: https://apps.apple.com/us/app/nrf-connect-device-manager/id1519423539

- Verified: published by Nordic Semiconductor ASA. An iOS app.
- Verified: described as a tool to update and manage devices running the nRF Connect SDK with the Device Manager module, over Bluetooth LE.
- Verified: listed features are echo, reset, firmware update over the air, file system, logs and stats.
- Not verified: that an Android version exists and has the same features.
- Not verified: that it works with a device that does not run the nRF Connect SDK, such as this board.
- What this project adds: a scripted, repeatable flow with timing and failure tests. That the app cannot do the same is an inference from its description as an interactive app, **not verified**.

### mcumgr-web

Source: https://github.com/boogie/mcumgr-web

- Verified: the README calls it the Web Bluetooth version of MCU Manager, for devices running the Mynewt OS.
- Verified: listed features include firmware upload over Bluetooth LE, image management (test, confirm, erase), reset and echo.
- Verified: Chrome and Edge on desktop are named as supported. Firefox and Safari are named as not supporting Web Bluetooth. It needs https or localhost.
- Not verified: support in other browsers or on Android. An earlier version of this page claimed Opera and Chrome on Android, from a search summary. Removed.
- Not verified: that it works against a Zephyr SMP server, or against this board. The README only names Mynewt.
- Not verified: how actively it is maintained.
- What this project adds: a transport that needs no radio, which makes the tests repeatable, and the failure tests themselves.

## Services where the device pulls its own update

Source for all four: the Zephyr OTA overview, https://docs.zephyrproject.org/latest/services/device_mgmt/ota.html

These need the device to reach a server by itself. This board has no working IP path in this project (see TRANSPORTS.md), so none of them could be tried here.
In each case the swap, test boot, confirm and revert underneath are MCUboot's. That they behave exactly like the MCUboot configuration measured here is an inference, **not verified**.

### Golioth

Second source: https://docs.golioth.io/firmware/golioth-firmware-sdk/firmware-upgrade/guide-ota

- Verified (Zephyr page): "Golioth is an IoT management platform that includes OTA updates." The connection uses TLS or DTLS, and the signed binary is confirmed by MCUboot before the upgrade.
- Verified (Golioth page): the page shows a banner, "Golioth is now a part of Canonical".
- Not verified: what that acquisition means for the service, whether new users can sign up, and on what terms.
- Not verified: how the device learns about a new release. An earlier version of this page said the device "watches the firmware revisions". That came from a search summary and was not found on the page that was read.
- Not verified: which boards, radios and Zephyr versions it supports.
- What this project adds: nothing on the fleet side. It documents the layer below, what MCUboot does with a bad or hung image.

### Memfault

Second source: https://docs.memfault.com/docs/mcu/zephyr-guide

- Verified (Zephyr page): "Memfault is a IoT observability platform that includes OTA management." Devices check periodically and download an update when one is available.
- Verified (Memfault page): the MCUboot backend needs a direct internet connection and `CONFIG_BOOTLOADER_MCUBOOT`. The client downloads the payload into the secondary MCUboot slot, then the device reboots into it.
- Not verified: the claim in an earlier version of this page that it offers "remote debugging and performance monitoring". That wording came from a search summary.
- What this project adds: nothing on monitoring or release management.

### Mender

Second source: https://docs.mender.io/operating-system-updates-zephyr/overview

- Verified (Zephyr page): mender-mcu "enables robust firmware updates on resource-constrained devices by integrating with Zephyr" and provides a default update module that integrates with MCUboot.
- Verified (Mender page): the reference implementation supports Zephyr 4.2.0 on boards that use MCUboot, with the ESP32-S3-DevKitC as reference board. The client periodically connects to the Mender server to report its software version and check for updates.
- Not verified: that the microcontroller support is a "preview, not recommended for production". A search summary of the Mender documentation said so. The page that was read only says "reference implementation".
- Not verified: that the MCU client lacks artifact compression, artifact signatures and delta updates. Same origin, not found on the page that was read.
- Removed: an earlier version of this page called Mender "long established for Linux devices". No source was checked for that.
- What this project adds: a worked example with the secondary slot on external flash. Whether Mender's reference board uses a different layout is **not verified**.

### Eclipse hawkBit

Second source: https://docs.zephyrproject.org/latest/samples/subsys/mgmt/hawkbit/README.html

- Verified (Zephyr page): "Eclipse hawkBit is an update server framework that uses polling on a REST api to detect firmware updates."
- Verified (sample page): Zephyr ships a client sample with a polling mode and a manual mode. "The MCUboot bootloader is required for hawkBit to function properly." The sample starts the server with Docker Compose, web interface on port 8088 and device API on port 8080.
- Not verified: its licence. An earlier version of this page called it "open source" without a source.
- What this project adds: the device side evidence. hawkBit is the closest match to this project's unbuilt stretch goal, a server that offers a version for a script or device to fetch.

## Also listed on the Zephyr OTA page, not looked at

UpdateHub, LwM2M firmware update, and a plain HTTP download library. Only their names and one line descriptions were read.

## What this project does not cover

These are gaps in this project. That each tool above fills them is **not verified** per tool.

- Managing many devices: groups, staged rollouts, scheduling, dashboards.
- Authenticating who is allowed to push an update.
- Devices that are not on the bench: no cable, intermittent connectivity, resuming a partial download.
- Monitoring a device after the update.

## What this project does have

These are statements about this repository, backed by `docs/RESULTS.md`.

- Every failure case is scripted, starts from a known flash state, and records the bootloader line that proves the result.
- Measured timings with raw data, including a swap of an image that nearly fills the slot.
- Three hardware level problems found and fixed, each with a before and after.

No claim is made that the tools above lack these. That was not checked.
