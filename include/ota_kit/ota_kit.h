/*
 * Copyright (c) 2026 Jotheesh Kummathi
 * SPDX-License-Identifier: Apache-2.0
 */

/* OTA kit: confirm a test image only when the application says it is healthy. */
#ifndef OTA_KIT_H_
#define OTA_KIT_H_

#include <stdbool.h>

/** Returns true when the application is healthy enough to keep this image. */
typedef bool (*ota_kit_health_cb_t)(void);

/**
 * Register the health check. Call it early in main().
 *
 * A test image is confirmed only if a check is registered and returns true when the
 * kit calls it, CONFIG_OTA_KIT_HEALTH_DELAY_S after boot. No check means no confirm,
 * and MCUboot reverts the image at the next reset.
 */
void ota_kit_set_health_check(ota_kit_health_cb_t cb);

/** True if the kit armed the watchdog. Always false without CONFIG_OTA_KIT_WATCHDOG. */
bool ota_kit_watchdog_armed(void);

#endif /* OTA_KIT_H_ */
