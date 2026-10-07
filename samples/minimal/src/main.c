/*
 * Copyright (c) 2026 Jotheesh Kummathi
 * SPDX-License-Identifier: Apache-2.0
 */

/* Smallest application that uses the OTA kit: register a health check, then do your work. */
#include <zephyr/kernel.h>
#include <ota_kit/ota_kit.h>

/* Replace with a real check: a sensor answers, a link is up, a self test passes. */
static bool health_ok(void)
{
	return true;
}

int main(void)
{
	ota_kit_set_health_check(health_ok);
	printk("ota_kit minimal sample, watchdog %s\n",
	       ota_kit_watchdog_armed() ? "armed" : "not used on this board");
	return 0;
}
