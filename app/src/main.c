/*
 * Copyright (c) 2026 Jotheesh Kummathi
 * SPDX-License-Identifier: Apache-2.0
 */

/* Example application for the OTA kit on disco_l475_iot1: a version dependent LED blink. */
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/hwinfo.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/dfu/mcuboot.h>
#include <zephyr/app_version.h>
#include <ota_kit/ota_kit.h>
#ifdef CONFIG_APP_ERASE_TRACE
#include <zephyr/mgmt/mcumgr/mgmt/mgmt.h>
#include <zephyr/mgmt/mcumgr/mgmt/callbacks.h>
/* IMG_MGMT_ID_ERASE. Its header needs MCUboot's include path, which the app does not have. */
#define SMP_IMAGE_ERASE 5
#endif

#if defined(CONFIG_APP_HANG) || defined(CONFIG_APP_HEALTH_FORCE_FAIL)
#warning "TEST IMAGE: built with a forced failure option. Never ship this build."
#endif

#if CONFIG_APP_PAD_BYTES > 0
/* Dead weight, only there to make the image big. Read once in main so the linker keeps it. */
static const uint8_t pad[CONFIG_APP_PAD_BYTES] = { [0 ... CONFIG_APP_PAD_BYTES - 1] = 0xA5 };
#endif

/* Blink rate shows which version is running: 1.0.x slow, anything newer fast. */
#define BLINK_MS (APP_VERSION_MINOR ? 200 : 1000)

/* Boards without an led0 alias, such as esp32_devkitc, run the same code without the blink. */
#define HAS_LED DT_NODE_EXISTS(DT_ALIAS(led0))
#if HAS_LED
static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
#endif

/* Healthy means: LED works and the slot 1 flash is reachable, so the next update can land. */
static bool health_ok(void)
{
	bool ok = device_is_ready(PARTITION_DEVICE(slot1_partition));

#if HAS_LED
	ok = ok && gpio_is_ready_dt(&led);
#endif

	if (IS_ENABLED(CONFIG_APP_HEALTH_FORCE_FAIL)) {
		ok = false;
	}
	return ok;
}

#ifdef CONFIG_APP_HANG_EARLY
/* Test images only: nothing of the application runs, not even the console driver. */
static int early_hang(void)
{
	for (;;) {
	}
	return 0;
}

SYS_INIT(early_hang, PRE_KERNEL_1, 0);
#endif

#ifdef CONFIG_APP_ERASE_TRACE
static enum mgmt_cb_return erase_trace(uint32_t event, enum mgmt_cb_return prev_status,
				       int32_t *rc, uint16_t *group, bool *abort_more,
				       void *data, size_t data_size)
{
	const struct mgmt_evt_op_cmd_arg *cmd = data;

	ARG_UNUSED(prev_status);
	ARG_UNUSED(rc);
	ARG_UNUSED(group);
	ARG_UNUSED(abort_more);
	ARG_UNUSED(data_size);

	if ((cmd->group == MGMT_GROUP_ID_IMAGE) && (cmd->id == SMP_IMAGE_ERASE)) {
		if (event == MGMT_EVT_OP_CMD_RECV) {
			printk("slot erase start\n");
		} else if (event == MGMT_EVT_OP_CMD_DONE) {
			printk("slot erase done\n");
		}
	}
	return MGMT_CB_OK;
}

static struct mgmt_callback erase_trace_cb = {
	.callback = erase_trace,
	.event_id = MGMT_EVT_OP_CMD_ALL,
};
#endif

int main(void)
{
	uint32_t cause = 0;

	ota_kit_set_health_check(health_ok);
#ifdef CONFIG_APP_ERASE_TRACE
	mgmt_callback_register(&erase_trace_cb);
#endif

	(void)hwinfo_get_reset_cause(&cause); /* cause stays 0 if it cannot be read */
	(void)hwinfo_clear_reset_cause();

	printk("OTA app v%s, blink %d ms, %s\n", APP_VERSION_STRING, BLINK_MS,
	       boot_is_img_confirmed() ? "confirmed" : "TEST boot, not confirmed yet");
	printk("watchdog %s, last reset by %s\n", ota_kit_watchdog_armed() ? "armed" : "NOT armed",
	       cause & RESET_WATCHDOG ? "WATCHDOG" : "other cause");

#if CONFIG_APP_PAD_BYTES > 0
	printk("padded image: %d extra bytes (0x%02x)\n", CONFIG_APP_PAD_BYTES,
	       *(volatile const uint8_t *)pad);
#endif

#if HAS_LED
	if (gpio_pin_configure_dt(&led, GPIO_OUTPUT_ACTIVE) != 0) {
		printk("LED init failed\n"); /* the health check will also see a dead LED port */
	}
#endif

	if (IS_ENABLED(CONFIG_APP_HANG)) {
		printk("simulated hang: spinning, watchdog will not be fed\n");
		while (1) {
			k_busy_wait(1000);
		}
	}

	while (IS_ENABLED(CONFIG_APP_CHATTER)) {
		printk(".");
		(void)k_msleep(1);
	}

	while (1) {
#if HAS_LED
		(void)gpio_pin_toggle_dt(&led);
#endif
		(void)k_msleep(BLINK_MS);
	}
	return 0;
}
