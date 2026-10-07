# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
#
# Zephyr module build file, see zephyr/module.yml. Not a standalone project.
if(CONFIG_OTA_KIT)
  zephyr_include_directories(include)
  zephyr_library()
  zephyr_library_sources(src/ota_kit.c)
  zephyr_library_sources_ifdef(CONFIG_OTA_KIT_TRANSPORT_BLE src/ota_kit_ble.c)
  zephyr_library_sources_ifdef(CONFIG_OTA_KIT_WIFI_UDP src/ota_kit_wifi.c)
  zephyr_linker_sources_ifdef(CONFIG_OTA_KIT_SIZE_GUARD SECTIONS linker/size_guard.ld)

  if(CONFIG_OTA_KIT_STRICT_WARNINGS)
    # Zephyr's own extended warning sets (the ones behind its W=1 and W=2 options, see
    # cmake/compiler/gcc/compiler_flags.cmake), for the kit and the application sources only.
    set(ota_kit_strict $<TARGET_PROPERTY:compiler,warning_dw_1>
                       $<TARGET_PROPERTY:compiler,warning_dw_2>)
    zephyr_library_compile_options(${ota_kit_strict})
    target_compile_options(app PRIVATE ${ota_kit_strict})
  endif()
endif()
