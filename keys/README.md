# Keys

This folder holds your signing key. No key is in the repository.

Make the key one time:

```sh
imgtool keygen -k keys/ota_signing.pem -t ecdsa-p256
```

**WARNING: Do not commit `keys/ota_signing.pem`. A person who has this file can sign firmware for your devices.**

Git ignores `*.pem` files in this folder. `scripts/build.sh` reads the key from here and builds its public half into MCUboot.
For encrypted images, `ENC=1 scripts/build.sh` reads `keys/ota_enc.pem`. See "Encrypted images" in [docs/RESULTS.md](../docs/RESULTS.md).
