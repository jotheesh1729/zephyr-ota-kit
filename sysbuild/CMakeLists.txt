# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
#
# Sysbuild part of the OTA kit module: applies the options in sysbuild/Kconfig to the images.
function(ota_kit_pre_cmake)
  if(NOT SB_CONFIG_BOOTLOADER_MCUBOOT)
    return()
  endif()

  if(SB_CONFIG_OTA_KIT)
    set_config_bool(${DEFAULT_IMAGE} CONFIG_OTA_KIT y)
    # MCUboot's default is y, but its ESP32 SoC configuration turns the check of slot 0 off.
    set_config_bool(mcuboot CONFIG_BOOT_VALIDATE_SLOT0 y)
  endif()
  if(SB_CONFIG_OTA_KIT_TRANSPORT_BLE)
    set_config_bool(${DEFAULT_IMAGE} CONFIG_OTA_KIT_TRANSPORT_BLE y)
  endif()

  if(SB_CONFIG_OTA_KIT_WIFI_UDP)
    set_config_bool(${DEFAULT_IMAGE} CONFIG_OTA_KIT_WIFI_UDP y)
  endif()

  if(SB_CONFIG_OTA_KIT_DOWNGRADE_PREVENTION)
    set_config_bool(mcuboot CONFIG_MCUBOOT_DOWNGRADE_PREVENTION y)
    set_config_bool(${DEFAULT_IMAGE} CONFIG_MCUBOOT_BOOTLOADER_NO_DOWNGRADE y)
  endif()

  if(SB_CONFIG_OTA_KIT_MCUBOOT_CONSOLE_LOG)
    set_config_bool(mcuboot CONFIG_SERIAL y)
    set_config_bool(mcuboot CONFIG_CONSOLE y)
    set_config_bool(mcuboot CONFIG_UART_CONSOLE y)
    set_config_bool(mcuboot CONFIG_MCUBOOT_LOG_LEVEL_INF y)
  endif()

  if(SB_CONFIG_OTA_KIT_MCUBOOT_WATCHDOG_TIMEOUT_MS GREATER 0)
    # MCUboot's own board file turns the driver on for some boards, not for the ESP32.
    set_config_bool(mcuboot CONFIG_WATCHDOG y)
    set_config_int(mcuboot CONFIG_BOOT_WATCHDOG_TIMEOUT_MS
                   ${SB_CONFIG_OTA_KIT_MCUBOOT_WATCHDOG_TIMEOUT_MS})
  endif()

  if(NOT "${SB_CONFIG_OTA_KIT_MCUBOOT_LOGICAL_SECTOR_SIZE}" STREQUAL "0x0")
    set_config_int(mcuboot CONFIG_MCUBOOT_LOGICAL_SECTOR_SIZE
                   ${SB_CONFIG_OTA_KIT_MCUBOOT_LOGICAL_SECTOR_SIZE})
    # the application's size guard has to use the same sector size
    set_config_int(${DEFAULT_IMAGE} CONFIG_OTA_KIT_SWAP_SECTOR_SIZE
                   ${SB_CONFIG_OTA_KIT_MCUBOOT_LOGICAL_SECTOR_SIZE})
    set_config_bool(mcuboot CONFIG_BOOT_MAX_IMG_SECTORS_AUTO n)
    set_config_int(mcuboot CONFIG_BOOT_MAX_IMG_SECTORS
                   ${SB_CONFIG_OTA_KIT_MCUBOOT_MAX_IMG_SECTORS})
  endif()
endfunction()
