/*
 * Copyright (c) 2026 Jotheesh Kummathi
 * SPDX-License-Identifier: Apache-2.0
 */

/*
 * OTA kit size guard: stop the build when the image is larger than MCUboot can swap.
 *
 * Swap using move needs one free sector in slot 0, and the image plus its trailer must
 * also fit in slot 1 (MCUboot design.md, "Swap using move"):
 *
 *   largest image = min((sectors in slot 0 - 1) x sector size, slot 1 size) - trailer
 *
 * Zephyr sizes the application by slot 0 alone. On a board where slot 0 is one sector
 * larger than slot 1, that leaves a gap in which an image builds, signs and uploads, and
 * is then refused by MCUboot. Measured on disco_l475_iot1: limit 876544 B, linker 880490 B.
 *
 * CONFIG_ROM_END_OFFSET is the trailer plus an estimate of the signature TLVs, as worked out
 * by MCUboot's sysbuild code. The estimate for ECDSA P256 is 150 B, the real TLVs here are
 * 151 B, and an ECDSA signature varies by a byte or two. An encrypted image adds a key TLV
 * of up to 129 B plus its 4 B header (MCUboot encrypted_images.md) that the estimate does
 * not include. OTA_KIT_TLV_MARGIN covers both, at the cost of 160 B of usable size.
 * _flash_used is everything from the MCUboot header to the end of the image.
 */
#define OTA_KIT_TLV_MARGIN 160
#include <zephyr/devicetree.h>

#define OTA_KIT_SLOT0 DT_NODELABEL(slot0_partition)
#define OTA_KIT_SLOT1 DT_NODELABEL(slot1_partition)

#if CONFIG_OTA_KIT_SWAP_SECTOR_SIZE > 0
#define OTA_KIT_SECTOR CONFIG_OTA_KIT_SWAP_SECTOR_SIZE
#else
/* flash -> partitions -> partition */
#define OTA_KIT_SECTOR DT_PROP_OR(DT_GPARENT(OTA_KIT_SLOT0), erase_block_size, 0)
#endif

#if OTA_KIT_SECTOR > 0 && CONFIG_ROM_END_OFFSET > 0
ota_kit_max_rom_size = MIN((DT_REG_SIZE(OTA_KIT_SLOT0) / OTA_KIT_SECTOR - 1) * OTA_KIT_SECTOR,
			   DT_REG_SIZE(OTA_KIT_SLOT1)) - CONFIG_ROM_END_OFFSET - OTA_KIT_TLV_MARGIN;
ota_kit_rom_size = _flash_used;
ASSERT(ota_kit_rom_size <= ota_kit_max_rom_size,
"
OTA kit size guard: this image is larger than MCUboot can swap.
  It would build, sign and upload, and MCUboot would then refuse it.
  Limit = min((sectors in slot 0 - 1) x sector size, slot 1 size) - trailer.
  Run scripts/ota_doctor.py on the build for the numbers (rule SIZE-01),
  or look up ota_kit_max_rom_size and ota_kit_rom_size in the map file.
  Make the application smaller, or the slots larger. See docs/DOCTOR.md.
")
#endif
