/*
 * Copyright (c) 2026 Jotheesh Kummathi
 * SPDX-License-Identifier: Apache-2.0
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/init.h>
#include <zephyr/drivers/watchdog.h>
#include <zephyr/dfu/mcuboot.h>
#include <ota_kit/ota_kit.h>

#if defined(CONFIG_OTA_KIT_REQUIRE_EXT_FLASH_RESET)
/* The flash device is the grandparent of the partition: flash -> partitions -> partition */
#define SLOT1_FLASH DT_GPARENT(DT_NODELABEL(slot1_partition))
#if DT_NODE_HAS_COMPAT(SLOT1_FLASH, st_stm32_qspi_nor)
BUILD_ASSERT(DT_PROP(SLOT1_FLASH, reset_cmd),
	     "slot 1 is on a QSPI flash without reset-cmd. Add reset-cmd and reset-cmd-wait "
	     "to the flash node, see CONFIG_OTA_KIT_REQUIRE_EXT_FLASH_RESET and docs/PORTING.md");
#endif
#endif

static ota_kit_health_cb_t health_cb;

#if defined(CONFIG_OTA_KIT_WATCHDOG)
BUILD_ASSERT(CONFIG_OTA_KIT_WATCHDOG_TIMEOUT_MS > (CONFIG_OTA_KIT_HEALTH_DELAY_S * 1000),
	     "the watchdog would fire before the health check runs");
BUILD_ASSERT((CONFIG_OTA_KIT_WATCHDOG_FEED_MS * 2) <= CONFIG_OTA_KIT_WATCHDOG_TIMEOUT_MS,
	     "feed period too close to the watchdog timeout");

static const struct device *const wdt = DEVICE_DT_GET(DT_ALIAS(watchdog0));
static int wdt_channel = -1;

/* MCUboot may already have started the watchdog, and it cannot be stopped. Take it over at once. */
static int watchdog_start(void)
{
	const struct wdt_timeout_cfg cfg = {
		.flags = WDT_FLAG_RESET_SOC,
		.window.max = CONFIG_OTA_KIT_WATCHDOG_TIMEOUT_MS,
	};

	if (device_is_ready(wdt)) {
		wdt_channel = wdt_install_timeout(wdt, &cfg);
		if ((wdt_channel >= 0) && (wdt_setup(wdt, WDT_OPT_PAUSE_HALTED_BY_DBG) != 0)) {
			wdt_channel = -1;
		}
	}
	return 0;
}
/* Before main(), so that an application that hangs on its first line is still covered. */
SYS_INIT(watchdog_start, APPLICATION, 0);
#endif

void ota_kit_set_health_check(ota_kit_health_cb_t cb)
{
	health_cb = cb;
}

bool ota_kit_watchdog_armed(void)
{
#if defined(CONFIG_OTA_KIT_WATCHDOG)
	return wdt_channel >= 0;
#else
	return false;
#endif
}

static bool health_ok(void)
{
	bool ok = (health_cb != NULL);

#if defined(CONFIG_OTA_KIT_WATCHDOG)
	if (wdt_channel < 0) {
		ok = false; /* without a watchdog a later hang would never be reverted */
	}
#endif
	return ok && health_cb();
}

/*
 * Feeds the watchdog and confirms a test image after the health window.
 *
 * Priority is one step above the SMP work queue and below main:
 * - If main (or anything above it) spins, this thread starves and the chip resets.
 * - A slot 1 erase in the SMP thread can busy poll an external flash for many seconds.
 *   It must not starve this thread, or the watchdog fires in the middle of an erase.
 * Not covered: a hang in the SMP thread itself or in lower priority threads.
 */
#define HEALTH_PRIO K_PRIO_PREEMPT(CONFIG_MCUMGR_TRANSPORT_WORKQUEUE_THREAD_PRIO - 1)
BUILD_ASSERT(HEALTH_PRIO > CONFIG_MAIN_THREAD_PRIORITY, "health thread must stay below main");

static void health_thread(void *a, void *b, void *c)
{
	bool decided = boot_is_img_confirmed();

	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);

	while (1) {
#if defined(CONFIG_OTA_KIT_WATCHDOG)
		if (wdt_channel >= 0) {
			(void)wdt_feed(wdt, wdt_channel); /* nothing useful to do if it fails */
		}
#endif
		if (!decided &&
		    (k_uptime_get() >= ((int64_t)CONFIG_OTA_KIT_HEALTH_DELAY_S * (int64_t)MSEC_PER_SEC))) {
			if (!health_ok()) {
				printk("health check FAILED, not confirming\n");
			} else if (boot_write_img_confirmed() == 0) {
				printk("health check OK, image confirmed\n");
			} else {
				printk("confirm write FAILED\n");
			}
			decided = true; /* decide once per boot */
		}
		(void)k_msleep(COND_CODE_1(CONFIG_OTA_KIT_WATCHDOG,
					   (CONFIG_OTA_KIT_WATCHDOG_FEED_MS), (1000)));
	}
}
K_THREAD_DEFINE(ota_kit_health, CONFIG_OTA_KIT_HEALTH_STACK_SIZE, health_thread,
		NULL, NULL, NULL, HEALTH_PRIO, 0, 0);
