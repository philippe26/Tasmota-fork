# My Contributions — branch `scada_projects`

Custom modifications applied on top of Tasmota `development` branch, targeting
SCADA/industrial use cases with MCP23017 I2C expanders, TM1638 displays and
DS18B20 temperature sensors.

Base version: **14.4.1** — custom build tag added to the patch byte
(`TASMOTA_BUILD`, `tasmota_version.h`).

---

## Build history (`TASMOTA_BUILD`)

| Build | Date       | Description |
|-------|------------|-------------|
| 0x80  | 2025-05-01 | LED/LEDLNK support — extend LED delegation to xdrv drivers (xdrv_66 TM1638, xdrv_67 MCP23xx) |
| 0x82  | 2025-05-29 | Topology support for MCP23xx — enforce I2C address recognition and ordering |
| 0x83  | 2025-06-01 | Display command response — add assigned relay/power index information |
| 0x84  | 2025-10-24 | I2C speed — bugfix dynamic speed change + new `I2cSpeed` command |
| 0x85  | 2026-03-21 | DS18B20 — prevent log flooding on sensor disconnect; allow disconnect/reconnect |
| 0x86  | 2026-04-04 | Berry API — add `tasmota.get_button_state(idx)` to read debounced button state from Berry |

---

## Detailed changes

### 0x86 — `tasmota.get_button_state(idx)` Berry binding (2026-04-04)

**Files:** `xdrv_52_3_berry_tasmota.ino`, `be_tasmota_lib.c`, `support_button_v4.ino`

Adds a new Berry function `tasmota.get_button_state(idx)` that returns the
debounced physical state of a button (0-based index):
- Returns `1` (PRESSED) or `0` (NOT_PRESSED), **normalized regardless of inversion**
- Returns `nil` if index is out of range
- `ButtonGetState()` now XORs `debounced_state` with `inverted_mask` bit so that
  `1=PRESSED` is always true whether the button is `Button`, `Button_n`, `Button_i`,
  or `Button_i_NP`

**Motivation:** buttons managed via MCP23017 over I2C do not reliably generate
multi-press events (DOUBLE/TRIPLE) because Tasmota's button counter relies on
GPIO edge timing. Reading the physical state at HOLD time allows reliable
simultaneous-press detection (e.g. btn1+btn2 HOLD → pump AUTO mode) without
depending on event timing.

---

### 0x85 — DS18B20 sensor robustness (2026-03-21 / 2026-03-22)

**Files:** `xsns_05_esp32_ds18x20.ino`

- Allow sensor disconnect and reconnect at runtime without requiring a reboot
- Fix null pointer dereference in DS18 alias rescan (`DSalias`) when a sensor
  is removed while aliases are configured

---

### 0x84 — I2C speed command + bugfix (2025-10-24 / 2026-03-14)

**Files:** `support_a_i2c.ino`

- New command `I2cSpeed <hz>` to set I2C bus speed at runtime
- Bugfix: dynamic speed change was not properly restored after bus re-init,
  causing the speed to revert to 100 kHz after certain operations

---

### 0x83 — Display command: assigned relay info (2025-06-01)

**Files:** `xdrv_13_display.ino`

- The `Display` command response now includes the relay/power index assigned
  to control the display backlight, allowing Berry scripts to verify the
  hardware configuration at startup

---

### 0x82 — MCP23xx Topology support (2025-05-29 / 2025-06-01)

**Files:** `xdrv_67_mcp23xxx.ino`, `support_command.ino`

- Add I2C topology discovery for MCP23017/MCP23008 expanders: enforce address
  recognition and ordering across the I2C bus
- Bugfixes for multi-chip configurations where button/relay offsets were
  incorrectly computed

---

### 0x80 — LED/LEDLNK delegation to xdrv (2025-01-05 / 2025-05-01)

**Files:** `xdrv_66_tm1638.ino`, `xdrv_67_mcp23xxx.ino`, `tasmota.ino`,
`support_tasmota.ino`, `tasmota.h`

- Extend the LED and LEDLNK subsystem to allow external drivers (xdrv) to
  claim and drive individual LEDs and link indicators
- TM1638 (xdrv_66): LEDs on the TM1638 display module can now be used as
  Tasmota status LEDs or relay indicators
- MCP23017 (xdrv_67): GPIO outputs on MCP23017 expanders can now serve as
  Tasmota LEDs/LEDLNK pins
- Enables richer status display on custom hardware without dedicated LED GPIO
  on the ESP32

---

## Build & deployment infrastructure

**Files:** `platformio.ini`, `platformio_override.ini`, `platformio_tasmota_cenv.ini`,
`partitions/`, `scripts/post_upload_to_syno.py`

- Custom PlatformIO environments for specific board targets
- Dedicated safeboot partition layout (`app2880k_fs256k_safeboot896k`)
- Post-build script: automatic firmware upload to Synology NAS (OTA/web)
- OTAURL environment variable bugfix in `platformio_tasmota_cenv.ini`

---

## Modified files summary

| File | Change |
|------|--------|
| `tasmota/include/tasmota_version.h` | Custom build version tracking |
| `tasmota/include/tasmota.h` | LED delegation hooks |
| `tasmota/include/i18n.h` | i18n strings for new commands |
| `tasmota/my_user_config.h` | Custom default configuration |
| `tasmota/user_config_override.h` | Per-build overrides |
| `tasmota/tasmota.ino` | LED subsystem extension |
| `tasmota/tasmota_support/support_a_i2c.ino` | I2cSpeed command + bugfix |
| `tasmota/tasmota_support/support_command.ino` | Topology command support |
| `tasmota/tasmota_support/support_tasmota.ino` | LED delegation |
| `tasmota/tasmota_xdrv_driver/xdrv_13_display.ino` | Display power index in response |
| `tasmota/tasmota_xdrv_driver/xdrv_52_3_berry_tasmota.ino` | `tasmota.get_button_state()` |
| `tasmota/tasmota_xdrv_driver/xdrv_66_tm1638.ino` | LED/LEDLNK support |
| `tasmota/tasmota_xdrv_driver/xdrv_67_mcp23xxx.ino` | LED/LEDLNK + topology |
| `tasmota/tasmota_xsns_sensor/xsns_05_esp32_ds18x20.ino` | DS18B20 robustness |
| `lib/libesp32/berry_tasmota/src/be_tasmota_lib.c` | `get_button_state` Berry registration |
| `platformio.ini` / `platformio_override.ini` / `platformio_tasmota_cenv.ini` | Build environments |
| `partitions/` | Custom partition tables |
| `scripts/post_upload_to_syno.py` | Synology OTA upload script |
