# Security

## What this project is

A demonstration of a firmware update path on a development board. It is not a product and has had no outside security review.
Read the security model in [docs/REFERENCE.md](docs/REFERENCE.md), and [docs/HAZARDS.md](docs/HAZARDS.md), first. Several serious weaknesses are known and documented, and are not vulnerabilities to report.

## Reporting a vulnerability

Please do not open a public issue for something that could be used against people running this code.

Use GitHub's private vulnerability reporting for this repository: the "Security" tab, then "Report a vulnerability".
If that button is not there, private reporting is not enabled for the repository. In that case open a public issue that only says you have a security report and asks for a private channel, with no details.

Useful in a report: what an attacker needs (physical access, radio range, a signing key), what they gain, the steps, and the build configuration. The output of `scripts/ota_doctor.py` on your build helps.

No response time is promised. This project is maintained in spare time by one person.

## In scope

Problems in what this repository adds:

- The kit: `src/`, `include/`, `Kconfig`, `sysbuild/`, `linker/`, `snippets/`.
- The host scripts: `scripts/ota_update.py`, `scripts/ota_doctor.py`, `scripts/build.sh`.
- The example configuration, if it makes a build less safe than the documentation says. For example: a way to get an image confirmed without the health check, a way around the downgrade check that does not need a debug probe, a way to use SMP over Bluetooth LE without pairing.
- The doctor reporting PASS for a configuration that one of its own rules is meant to catch.
- Anything in the repository that should not be public: a private key, a token, personal data.

## Out of scope

- **Bugs in Zephyr, MCUboot, the STM32 HAL or the Python packages.** Report those to the projects themselves. Both Zephyr and MCUboot have their own security reporting process. If the problem only shows through this kit's configuration, it is welcome here too.
- **The documented weaknesses**, including:
  - The debug port is open and readout protection is off, so firmware and keys can be read and replaced with a probe.
  - SMP over UART has no authentication.
  - Bluetooth pairing is "Just Works": the first device to pair holds the only bond.
  - Image encryption is optional, not enforced, and its key is stored in the device.
  - The device reboots for an update whenever the host asks.
  - Power loss is tested only as a clean cut with one image size.
- **The development keys.** `keys/ota_signing.pub.pem` belongs to a throwaway key pair made for the tests. MCUboot's own bundled keys are public by design. Do not use either.
- Attacks that need the signing key.

## Supported versions

Only the latest commit on the main branch. There are no maintained release branches.
