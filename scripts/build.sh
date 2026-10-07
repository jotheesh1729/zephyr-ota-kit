#!/bin/sh
# Copyright (c) 2026 Jotheesh Kummathi
# SPDX-License-Identifier: Apache-2.0
# Build MCUboot + signed app.
# BOARD=<zephyr board target> builds for another board, into build/<name>-v<version>.
# Tried so far: esp32_devkitc/esp32/procpu (output in build/esp32-v<version>).
# Usage: [KEY=path/to/key.pem] [VARIANT=ble] scripts/build.sh [MAJOR.MINOR.PATCH] [west args] [-DCMAKE_ARGS]
# Example: scripts/build.sh 1.1.0 -p always
#          scripts/build.sh 2.0.1 -DCONFIG_APP_HEALTH_FORCE_FAIL=y
#          VARIANT=ble scripts/build.sh 1.0.0      (adds the ota-kit-ble snippet)
#          VARIANT=wifi BOARD=esp32_devkitc/esp32/procpu scripts/build.sh 1.0.0   (ota-kit-wifi)
#          ENC=1 scripts/build.sh 1.0.0            (encrypted updates, output in build/enc-v1.0.0)
# Output: build/v<version>/app/zephyr/zephyr.signed.bin, or build/ble-v<version>/... for VARIANT=ble
# Needs: source ~/zephyrproject/.venv/bin/activate
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
KEY=$(realpath "${KEY:-$ROOT/keys/ota_signing.pem}")
VER=1.0.0
case "$1" in [0-9]*) VER=$1; shift ;; esac

# -D arguments go to CMake, everything else to west build
# The kit is a Zephyr module in this repository, turned on by its snippets.
WEST_ARGS="-S ota-kit" CMAKE_ARGS="-DEXTRA_ZEPHYR_MODULES=$ROOT"
BOARD=${BOARD:-disco_l475_iot1}
case "$BOARD" in
  disco_l475_iot1*) PRE="" ;;
  esp32_devkitc*) PRE="esp32-" ;;
  *) PRE="$(echo "$BOARD" | cut -d/ -f1)-" ;;
esac
DIR="${PRE}v$VER"
if [ "$VARIANT" = wifi ]; then
  WEST_ARGS="$WEST_ARGS -S ota-kit-wifi" DIR="${PRE}wifi-v$VER"
fi
if [ "$VARIANT" = ble ]; then
  WEST_ARGS="$WEST_ARGS -S ota-kit-ble" DIR="${PRE}ble-v$VER"
fi
# ENC=1: encrypted updates. MCUboot gets the private half of keys/ota_enc.pem, the update is
# build/enc-v<version>/app/zephyr/zephyr.signed.encrypted.bin. Not the default, see docs/RESULTS.md.
if [ -n "$ENC" ]; then
  ENC_KEY=$(realpath "${ENC_KEY:-$ROOT/keys/ota_enc.pem}")
  # SAVE_ENCTLV: slot 1 and its swap metadata are on the external flash here. Without this
  # option MCUboot writes the plain AES key there during a swap (MCUboot encrypted_images.md).
  CMAKE_ARGS="$CMAKE_ARGS -DSB_CONFIG_BOOT_ENCRYPTION=y -DSB_CONFIG_BOOT_ENCRYPTION_KEY_FILE=\"$ENC_KEY\""
  CMAKE_ARGS="$CMAKE_ARGS -Dmcuboot_CONFIG_BOOT_SWAP_SAVE_ENCTLV=y"
  DIR="enc-$DIR"
fi
for a in "$@"; do
  case "$a" in -D*) CMAKE_ARGS="$CMAKE_ARGS $a" ;; *) WEST_ARGS="$WEST_ARGS $a" ;; esac
done

# Zephyr reads the version from app/VERSION. Rewrite it for this build, restore after.
cp "$ROOT/app/VERSION" "$ROOT/app/VERSION.orig"
trap 'mv "$ROOT/app/VERSION.orig" "$ROOT/app/VERSION"' EXIT
IFS=. read -r MA MI PA <<EOV
$VER
EOV
printf 'VERSION_MAJOR = %s\nVERSION_MINOR = %s\nPATCHLEVEL = %s\nVERSION_TWEAK = 0\nEXTRAVERSION =\n' \
  "$MA" "$MI" "$PA" > "$ROOT/app/VERSION"

# west build only works from inside the west workspace
cd "${ZEPHYR_BASE:-$HOME/zephyrproject/zephyr}"
west build -b "$BOARD" --sysbuild -d "$ROOT/build/$DIR" "$ROOT/app" $WEST_ARGS -- \
  -DSB_CONFIG_BOOT_SIGNATURE_KEY_FILE=\"$KEY\" $CMAKE_ARGS
