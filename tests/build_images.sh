#!/bin/sh
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
# Build the baseline and every test image into build/test_images/.
# With VARIANT=ble the images include the BLE transport and go to build/test_images_ble/.
# With BOARD=esp32_devkitc/esp32/procpu the images go to build/test_images_esp32/.
# Needs: source ~/zephyrproject/.venv/bin/activate
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
P="" OUT=$ROOT/build/test_images
[ "$VARIANT" = ble ] && P="ble-" OUT=$ROOT/build/test_images_ble
[ "$VARIANT" = wifi ] && P="wifi-" OUT=$ROOT/build/test_images_wifi
# imgtool arguments for the image without a signature, the same ones Zephyr uses for the board:
# header 0x400, slot 0 size 868 K, write block 8.
NOSIG_ARGS="--header-size 0x400 --slot-size 0xd9000 --align 8"
case "$BOARD" in esp32*)
  # ESP32: header 0x20 (CONFIG_ROM_START_OFFSET), slot 0 size 1344 K, write block 4.
  P="esp32-$P" OUT=${OUT}_esp32 NOSIG_ARGS="--header-size 0x20 --slot-size 0x150000 --align 4" ;;
esac
export VARIANT
mkdir -p "$OUT"
cd "$ROOT"

build() { scripts/build.sh "$@" > "$OUT/build_$1.log" 2>&1 || { tail -30 "$OUT/build_$1.log"; exit 1; }; }
bin() { echo "$ROOT/build/${P}v$1/app/zephyr/zephyr$2.bin"; }

# A second key that MCUboot does not know
[ -f keys/wrong_key.pem ] || imgtool keygen -k keys/wrong_key.pem -t ecdsa-p256

build 1.0.0                                   # baseline, flashed over SWD
build 2.0.0
cp "$(bin 2.0.0 .signed)" "$OUT/v2.0.0-good.bin"

build 2.0.1 -DCONFIG_APP_HEALTH_FORCE_FAIL=y
cp "$(bin 2.0.1 .signed)" "$OUT/v2.0.1-nohealth.bin"

KEY=keys/wrong_key.pem build 2.0.2
cp "$(bin 2.0.2 .signed)" "$OUT/v2.0.2-badkey.bin"

build 2.0.3
# Raw linker output: no MCUboot header, no hash, no signature
cp "$(bin 2.0.3 "")" "$OUT/v2.0.3-unsigned.bin"
# Extra case: MCUboot header and SHA256, but no signature (imgtool without a key).
imgtool sign --version 2.0.3 $NOSIG_ARGS \
  "$(bin 2.0.3 "")" "$OUT/v2.0.3-nosig.bin"

build 2.0.4
# Flip 4 payload bytes at 0x2000 after signing. The header ends before that and stays intact.
python3 - "$(bin 2.0.4 .signed)" "$OUT/v2.0.4-corrupt.bin" <<'PY'
import sys
d = bytearray(open(sys.argv[1], "rb").read())
d[0x2000:0x2004] = bytes(b ^ 0xFF for b in d[0x2000:0x2004])
open(sys.argv[2], "wb").write(d)
PY

build 2.0.5 -DCONFIG_APP_HANG=y
cp "$(bin 2.0.5 .signed)" "$OUT/v2.0.5-hang.bin"

build 2.0.6 -DCONFIG_APP_HANG_EARLY=y
cp "$(bin 2.0.6 .signed)" "$OUT/v2.0.6-earlyhang.bin"

# Downgrade test: the baseline image offered again as an "update"
cp "$(bin 1.0.0 .signed)" "$OUT/v1.0.0-old.bin"

# Measurement images: a second normal version, and one that nearly fills slot 1
build 1.1.0
# The BLE app is 72 K bigger, this padding would not fit. Not built for the ESP32 either.
if [ -z "$VARIANT" ] && [ -z "${BOARD##disco*}" ]; then
  build 1.3.0 -DCONFIG_APP_PAD_BYTES=812000
  cp "$(bin 1.3.0 .signed)" "$OUT/v1.3.0-big.bin"
fi

ls -l "$OUT"/*.bin
