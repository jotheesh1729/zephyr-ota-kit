# Transport spike

Question: can the update run over the board's own radios instead of the UART?

Checked on 2026-10-05 with Zephyr `v4.4.0-13485-g133c2eb7d3cb` on a B-L475E-IOT01A. Time box: 90 minutes.
The Wi-Fi part is a spike and stays one. BLE was taken further in the first BLE series and went through the failure suite.
Neither radio is part of the default build.

## Summary

| Transport | Status | One line reason |
|---|---|---|
| UART (ST-LINK VCP) | Tested | Full failure suite and 20 measured runs, see RESULTS.md |
| BLE (SPBTLE-RF module) | Tested | Full failure suite once and 20 measured runs over an encrypted link (the first BLE series) |
| Wi-Fi driver (ISM43362 module) | Partial | Module answers and scans. Joining a network was not tested |
| SMP over UDP on that Wi-Fi driver | Not working | The driver does not support the socket calls the SMP UDP transport makes |
| Wi-Fi, SMP over UDP, on an ESP32 (`esp32_devkitc`) | Tested | 30 of 30 update runs and the failure suite, 9 of 9 cases, two passes (the first Wi-Fi session and the second Wi-Fi session). No encryption, no authentication |

## BLE: tested

The transport spike showed one update over BLE in a spike. The first BLE series hardened it and ran the test suite over it.
Since the module build the BLE code is part of the module (`src/ota_kit_ble.c`), and the advertised name is `ota-kit`. The measurements below were taken before that, when the name was `ota-stm32`. On the module build, cases 1 and 8 were rerun over BLE and passed.

Build and use:

```sh
VARIANT=ble scripts/build.sh 1.0.0            # adds the ota-kit-ble snippet, output in build/ble-v1.0.0
scripts/ota_update.py build/ble-v1.1.0/app/zephyr/zephyr.signed.bin --ble ota-kit
```

Tests and measurements pick the transport from `tests/config.toml` (`transport = "uart"` or `"ble"`).
The boot log is always read from the UART, also when SMP runs over BLE.

### Support in the installed Zephyr

- Board file lists `bluetooth` as supported (`boards/st/disco_l475_iot1/disco_l475_iot1.yaml`).
- Devicetree: `hci_spi: spbtle-rf@0`, compatible `st,hci-spi-v1`, chosen as `zephyr,bt-hci`.
- Driver: `drivers/bluetooth/hci/hci_spi_st.c`. Its Kconfig help says "Current driver supports: ST BLUENRG-MS".
- Zephyr runs the Bluetooth host. The module is used as a controller only (`req-ll-only` in the devicetree).

### Re-advertising

The spike stopped advertising after the first connection. Now advertising restarts from the `recycled` connection callback.

| Test | Result |
|---|---|
| 5 connect, read state, disconnect cycles, no reset, client default 2.5 s connect timeout | 4 of 5. One host side timeout |
| Same, 20 s connect timeout | 5 of 5, connect time 1.2 to 2.1 s |

The connect time is close to the client's 2.5 s default, so the scripts use 20 s and retry up to 3 times. Every retry is logged.

### ATT MTU and data length

From the documentation:

- The board documentation calls the module "Bluetooth V4.1". Data length extension came with Bluetooth 4.2.
- A search result summary of ST community posts says the BlueNRG-MS has no data length extension. **Not verified**: those posts were not read directly, and no ST datasheet was checked.

From tests on the board:

| Setting | Negotiated ATT payload | Upload | Runs |
|---|---|---|---|
| Zephyr defaults | 20 bytes | 93583 B in 39.91 s, 2345 B/s | 1 |
| `BT_L2CAP_TX_MTU=247`, `BT_BUF_ACL_RX_SIZE=251` | 244 bytes | 93862 B in 27.45 s, 3419 B/s | 1 |

- A larger ATT MTU is accepted. The host negotiates it and fragments it over the link.
- The link layer still uses 27 byte packets: `CONFIG_BT_BUF_ACL_TX_SIZE` stays at 27, and Zephyr warns at boot that the controller offers a single ACL buffer.
- Whether a data length update was ever attempted or refused on the air was not captured.
- The larger MTU is now the default with `CONFIG_OTA_KIT_TRANSPORT_BLE` (root `Kconfig`). RAM cost: 3724 B.

### Link security

What Zephyr offers for the SMP characteristic (`subsys/mgmt/mcumgr/transport/Kconfig.bluetooth`):

| Option | Meaning |
|---|---|
| `MCUMGR_TRANSPORT_BT_PERM_RW` | Anyone who connects can use it. This was the spike. |
| `MCUMGR_TRANSPORT_BT_PERM_RW_ENCRYPT` | Needs an encrypted link, so the central must pair. |
| `MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN` | Needs an encrypted and authenticated link, so pairing needs a passkey or similar. |

Enabled: `PERM_RW_ENCRYPT`, the cheapest one that works here.

What it took:

1. `CONFIG_BT_SMP=y`. Pairing works with this controller: the laptop reports "Pairing successful", `LegacyPairing: no`.
2. Bond storage: `CONFIG_BT_SETTINGS=y` with NVS in the 32 K storage partition.
3. A fixed address. Without it the bond was useless after every reset, and every update ends in a reset.
   - Cause: the board came up with a new random address on each boot (C2:19.. then C3:9B.. after one reset).
   - Zephyr only stores an automatically created random identity when `CONFIG_BT_PRIVACY` is on (`bt_setup_random_id_addr()` in `subsys/bluetooth/host/id.c`).
   - With `CONFIG_BT_PRIVACY=y` pairing failed in the one attempt made. Cause not investigated.
   - Fix used: before `bt_enable()` the app creates a public address from the chip's unique ID. The driver writes it to the controller.

Result after the fix: pair once, reset the board, 5 of 5 encrypted sessions without pairing again.

What this protects, and what it does not:

- Protects: the link is encrypted. A device that has not paired cannot use the SMP service.
- Does not protect: pairing is "Just Works". It does not prove who the central is, and it has no protection against a man in the middle during pairing.
- The board keeps one bond and does not overwrite it (`CONFIG_BT_MAX_PAIRED=1`, `BT_KEYS_OVERWRITE_OLDEST` off). So the first device to pair should be the only one that can ever use SMP, until the storage partition is erased. **Not tested**: there was no second central to try it with.
- Before that first pairing, anyone in range can take the slot. There is no button press or pairing window.
- The address is made from the chip ID and is not from a registered address block. Fine on a bench, not for a product.
- The image signature check does not depend on any of this. An unsigned or wrongly signed image is still refused by MCUboot (cases 3, 4b, 5 below).

Not done: `PERM_RW_AUTHEN` with a passkey. It needs a passkey shown on the board and typed on the host, and an agent on the host to automate it for the tests.

### Cost

| Build | App flash | App RAM |
|---|---|---|
| UART only | 47700 B | 15104 B |
| + BLE, defaults (spike) | 93432 B | 29118 B |
| + larger MTU | 93712 B | 32842 B |
| + pairing, encryption, bond storage (final) | 119596 B | 34414 B |

- Security adds 25884 B of flash and 1572 B of RAM.
- Speed: no slowdown seen. Unencrypted at the same MTU: 3419 B/s (1 run). Encrypted: 3568 B/s mean (20 runs).
- Time: the pairing step in the test baseline is about 33 s of fixed waits (10 s scan, then pair and disconnect). It is needed once, and again after every full flash erase.

### Failure suite over BLE, 1 pass

Same images, same expectations, same baseline as on UART, plus a pairing step after each flash erase.
Raw table: `tests/last_run_ble.md`. Logs: `tests/logs_ble/`.

| Case | Result over BLE | Same as UART? |
|---|---|---|
| 1 good | PASS | yes |
| 2 nohealth, rollback after reset | PASS | yes |
| 3 badkey | PASS | yes |
| 4 unsigned raw | PASS, different path (refused at upload) | yes, same different path |
| 4b nosig | PASS | yes |
| 5 corrupt | PASS | yes |
| 6 interrupted upload | PASS, killed at 60059 of 119747 B | yes |
| 8 hang, watchdog | PASS, chip reset 10.1 s after the hang | yes |
| 10 reset during erase | not run | UART only: the test writes a raw frame to the serial port |

### 20 update runs over BLE

Raw data: `docs/data/update_runs_ble_first_series.csv`. The board alternates between v1.0.0 and v1.1.0, link encrypted.

| Metric | Min | Mean | Median | Max | Std dev |
|---|---|---|---|---|---|
| Signed image size | 119739 B | 119742.5 B | 119742.5 B | 119746 B | |
| Upload time | 32.49 s | 33.60 s | 33.16 s | 36.27 s | 1.241 s |
| MCUboot + swap (19 of 20 runs) | 7.46 s | 7.81 s | 7.72 s | 8.23 s | 0.226 s |
| Total, upload start to confirmed | 52.33 s | 53.67 s | 53.25 s | 56.75 s | 1.357 s |

Success rate: 20 of 20.

### Differences from UART

| | UART | BLE |
|---|---|---|
| Image size | 47850 B | 119742 B, the BLE stack and pairing add 72 K |
| Upload throughput | about 5.7 kB/s | about 3.6 kB/s |
| Upload time | 8.37 s | 33.60 s. 2.5 times the data at 0.6 times the speed |
| MCUboot + swap | 4.41 s | 7.81 s. Caused by the larger image, not by the transport |
| Total | 18.30 s | 53.67 s |
| Spread of the total (std dev) | 0.024 s | 1.357 s |
| Setup | none | pair once, and again after every full flash erase |
| Connect retries | none needed | 1 in the suite, 1 in the 20 runs, both succeeded on the second try |
| Failure suite | 5 passes, then 1 on the final firmware | 1 pass |
| Near full slot image | measured | not measured, the padded image does not fit next to the BLE stack |

Other things seen:

- One of the 20 runs has no swap time. The host missed the first MCUboot line after the reset. The run itself succeeded.
- The times are not a like for like transport comparison, because the images differ in size. Throughput is the comparable number.
- The BLE numbers are from one laptop adapter with the board on the same desk. The distance was not measured. A scan in the transport spike showed RSSI -53.

### Limits

- Two passes of the failure suite in total: one in the first BLE series, one in the BLE regression on the final firmware with the downgrade case added. The BLE regression also has 5 more update runs, with uploads about 7% slower than here. See the BLE regression in RESULTS.md.
- Second central being refused: not tested.
- No test of range, interference, or a phone as the central.
- Not tested with nRF Connect Device Manager or mcumgr-web.

## Wi-Fi driver: partial

### Support in the installed Zephyr

- Devicetree: `wifi0: ism43362@1`, compatible `inventek,eswifi`, on SPI3.
- Driver: `drivers/wifi/eswifi/`, an offloaded driver. The module runs its own TCP/IP stack and Zephyr talks to it with AT commands.
- The board file does not list Wi-Fi or networking under `supported`.

### What was tried

Zephyr's own `samples/net/wifi/shell`, built for the board.

- As shipped it does not link: `region RAM overflowed by 5068 bytes`. The driver alone asks for a 51200 byte heap (`HEAP_MEM_POOL_ADD_SIZE_ESWIFI`), on a board with 96 K of RAM.
- With smaller stacks and buffer counts (`MAIN_STACK_SIZE=2048`, `SHELL_STACK_SIZE=3072`, 4 packets and 8 buffers each way) it links: RAM 93340 B of 96 K (94.95%).

### Evidence

```
uart:~$ wifi scan
Scan requested
(16 networks listed, 2.4 GHz, with channel, RSSI and security)
Scan request done

uart:~$ net iface
Interface wlan0 (IP Offload) [1]
Link addr : XX:XX:XX:XX:XX:XX   (the module's MAC address, masked)
Device    : ism43362@1
Status    : oper=UP, admin=UP, carrier=ON
```

The network names are left out on purpose.

### Not tested

Joining a network, DHCP, and any data transfer. That needs Wi-Fi credentials, which were not available during the spike.

## SMP over UDP on the eS-WiFi driver: not working

### Evidence from the code

The SMP UDP transport (`subsys/mgmt/mcumgr/transport/src/smp_udp.c`) receives with a source address and replies to that address:

```c
int len = zsock_recvfrom(conf->sock, conf->recv_buffer, CONFIG_MCUMGR_TRANSPORT_UDP_MTU, 0, &addr, &addr_len);
ret = zsock_sendto(smp_udp_configs.ipv4.sock, nb->data, nb->len, 0, addr, sizeof(*addr));
```

The eS-WiFi socket offload (`drivers/wifi/eswifi/eswifi_socket_offload.c`) refuses both when an address is passed:

```c
static ssize_t eswifi_socket_recvfrom(...)
{
	if (fromlen != NULL) {
		errno = EOPNOTSUPP;
		return -1;
	}
static ssize_t eswifi_socket_sendto(...)
{
	if (to != NULL) {
		errno = EOPNOTSUPP;
		return -1;
	}
```

### Evidence from the board

Built with `scripts/build.sh 9.1.0 -DEXTRA_CONF_FILE=spikes/wifi_udp.conf` (the firmware of the transport spike). It links (RAM 92420 B of 96 K, 94.01%) and boots:

```
OTA app v9.1.0, blink 200 ms, confirmed
watchdog armed, last reset by other cause
<inf> smp_udp: Started (IPv4)
<err> smp_udp: recvfrom error (IPv4): 95, -1
<err> smp_udp: recvfrom error (IPv4): 95, -1
(repeats without pause)
```

Error 95 is `EOPNOTSUPP`. The failing call retries in a tight loop.
The board also kept resetting during this test (3 boots seen in 25 s). The likely cause is the watchdog, with the feeder thread starved by that loop. That cause was not confirmed.
All of this happens before any network is joined.

### What it would take

- A driver change so that `recvfrom` reports the sender and `sendto` accepts a destination, if the module's AT command set can provide them. Not investigated.
- Or a different design that fits the driver: the device opens a TCP or UDP client connection to a server and pulls the image, instead of serving SMP.
- Either way the RAM budget is tight: over 90 K of 96 K is used before any application code is added.

## Wi-Fi and SMP over UDP on the ESP32: tested

The rows above are about the STM32 board, where SMP over UDP does not work. On the second board, an ESP32 WROOM-32, Zephyr has a native Wi-Fi driver and the SMP UDP transport runs.
Everything is in [BOARD_ESP32.md](BOARD_ESP32.md), "Wi-Fi, SMP over UDP". In short:

- Kit option `OTA_KIT_WIFI_UDP`, snippet `ota-kit-wifi`. UART stays the console and stays an SMP transport.
- Image 682 K against 160 K for UART. RAM use 141 K against 24 K.
- 30 of 30 update runs. Upload of 682 K: median 7.82 s. Upload start to confirmed: median 31.03 s.
- Failure suite, two passes: 9 of 9 cases each. A reset 100, 300 and 500 ms into a slot erase that was asked for over UDP: the old image ran each time.
- The host client needed two changes: drop duplicate or late answers, and wait after a reset until the board has joined the network again (4 to 12 s).
- The network name and passphrase are stored on the board, not in the build. `scripts/wifi_provision.py`.

### Security

SMP over UDP has no encryption and no authentication. Port 1337 answers any host that can reach the board.

| A person on the same network can | Checked |
|---|---|
| Upload a file to slot 1 | yes, it is what the update does. No credential is involved |
| Erase slot 1 | yes, the test baseline does it over UDP |
| Reset the board at any time | yes, the update does it over UDP |
| Read which versions are installed | yes |
| See an update in clear text | not run, follows from the protocol |
| Make an unsigned or modified image boot | **no**. Cases 3, 4b and 5 over Wi-Fi: rejected by MCUboot |
| Install an older signed image | **no**. Case 7 over Wi-Fi: erased by downgrade prevention |
| Run shell commands | **no**. Refused with return code 11 once a network is stored |

A person on the network can keep the board resetting or keep slot 1 erased, so that no update gets through. The kit has no defence against that.
Hazards HAZ-16 and HAZ-17 in [HAZARDS.md](HAZARDS.md). DTLS for SMP over UDP was not looked at.

## Not looked at

- The board's sub GHz radio (SPSGRF) and NFC tag.
- USB CDC ACM as an SMP transport.
- DTLS for SMP over UDP.
