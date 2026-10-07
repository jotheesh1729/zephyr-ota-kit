/*
 * Copyright (c) 2026 Jotheesh Kummathi
 * SPDX-License-Identifier: Apache-2.0
 */

/* BLE transport: advertise the SMP service. Built with CONFIG_OTA_KIT_TRANSPORT_BLE. */
#include <zephyr/kernel.h>
#include <zephyr/drivers/hwinfo.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/mgmt/mcumgr/transport/smp_bt.h>
#include <zephyr/settings/settings.h>

/*
 * At file scope on purpose: BT_DATA_BYTES expands to a compound literal, which is only a
 * constant initializer outside a function.
 */
static const struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, SMP_BT_SVC_UUID_VAL),
};

static const struct bt_data sd[] = {
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1U),
};

static void adv_start(struct k_work *work)
{
	int rc = bt_le_adv_start(BT_LE_ADV_CONN_FAST_1, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));

	ARG_UNUSED(work);
	if ((rc != 0) && (rc != -EALREADY)) {
		printk("BLE: advertising start failed %d\n", rc);
	}
}
static K_WORK_DEFINE(adv_work, adv_start);

/* Called when a connection object is free again, which is when advertising can restart. */
static void on_recycled(void)
{
	(void)k_work_submit(&adv_work);
}

/* One line per connection on the console: what the link actually negotiated. */
static void on_disconnected(struct bt_conn *conn, uint8_t reason)
{
	struct bt_conn_info info;

	if (bt_conn_get_info(conn, &info) == 0) {
		printk("BLE: disconnected, reason 0x%02x, security level %d\n", reason,
		       info.security.level);
	}
}

BT_CONN_CB_DEFINE(conn_cb) = {
	.disconnected = on_disconnected,
	.recycled = on_recycled,
};

static void ble_thread(void *a, void *b, void *c)
{
	int rc;

	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);

	if (IS_ENABLED(CONFIG_OTA_KIT_BLE_DEVICE_ADDR_FROM_CHIP_ID)) {
		/*
		 * Bonds only survive a reset if the address does. The stack would pick a new
		 * random address on every boot, so give the controller a fixed public address
		 * made from the chip's unique ID.
		 */
		/* ponytail: not a registered address block, fine on a bench, not for a product */
		bt_addr_le_t addr = { .type = BT_ADDR_LE_PUBLIC };
		uint8_t id[12];

		if (hwinfo_get_device_id(id, sizeof(id)) >= (int)sizeof(addr.a.val)) {
			(void)memcpy(addr.a.val, id, sizeof(addr.a.val));
			if (bt_id_create(&addr, NULL) < 0) {
				printk("BLE: fixed address not set, bonds will not survive a reset\n");
			}
		}
	}

	rc = bt_enable(NULL);

	printk("BLE: bt_enable %d\n", rc);
	if (rc == 0) {
		if (IS_ENABLED(CONFIG_BT_SETTINGS)) {
			if (settings_load() != 0) { /* bonds */
				printk("BLE: could not load settings, the host has to pair again\n");
			}
		}
		(void)k_work_submit(&adv_work);
	}
}
K_THREAD_DEFINE(ota_kit_ble, 2048, ble_thread, NULL, NULL, NULL, 7, 0, 0);
