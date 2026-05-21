# gpio-template tools

Two tools to create and convert Tasmota GPIO module templates:

| Tool | Description |
|------|-------------|
| `gpio-template-ui.py` | Graphical editor — mimics Tasmota's web configurator |
| `gpio-template-convert.py` | Command-line encoder/decoder |

Both work with two formats:

- **Human JSON** — readable, uses symbolic GPIO names (`LED1_INV_OPENDRAIN`, `KEY1`, …)
- **Tasmota JSON** — compact numeric format pasted in *Configuration > Other > Template*

The GPIO symbol table is parsed live from `tasmota/include/tasmota_template.h`, so
numeric IDs always match the current firmware build — renaming or reordering GPIOs in
the enum is handled automatically.

## Graphical UI

```bash
python3 gpio-template-ui.py [--input FILE] [--based-on PRESET] [--version]
```

Options:
- `--input FILE` — open a template file on startup (human or Tasmota JSON)
- `--based-on NAME` — start from a hardware preset (`ESP32`, `ESP32-S3`, `ESP32-C3`, `ESP8266`, …)
- `--version` — print version and exit (no display required)

Features:
- One row per GPIO slot (single-column layout like Tasmota web UI)
- Index dropdown hidden when only one instance is possible
- **New…** dialog: choose hardware preset (ESP32, ESP32-S3, ESP32-C3, ESP8266, …)
  to get the correct GPIO count and physical pin numbers automatically
- **Topology mode**: enter e.g. `16,0,8` in the Topology field and click Apply
  to split the template into one table per device (offset shown per table)
- **Open** human JSON or encoded Tasmota JSON
- **Save / Save As** as human JSON
- **View** button: encodes to Tasmota compact JSON, copies to clipboard,
  shows popup — ready to paste in *Configuration > Other > Template*

Hardware presets:

| Preset | User pins | Description |
|--------|-----------|-------------|
| `ESP32` | 36 | ESP32 Generic / DevKit |
| `ESP32-S2` | 36 | ESP32-S2 |
| `ESP32-S3` | 38 | ESP32-S3 |
| `ESP32-C3` | 22 | ESP32-C3 |
| `ESP32-C6` | 31 | ESP32-C6 |
| `ESP8266` | 14 | ESP8266 / Wemos D1 Mini |
| `Generic-36` | 36 | 36 flat slots |
| `Generic-16` | 16 | 16 flat slots (I2C expander) |

## Encoding

```
template_value = (gpio_enum_index << 5) | pin_index
```

- `gpio_enum_index` — position of the GPIO in `UserSelectablePins` enum
- `pin_index` — 0-based instance (LED1=0, LED2=1 …)

## Requirements

Python 3.10+. No external dependencies (tkinter is part of the standard library).

## Command-line usage

```bash
# Show version and header path
python3 gpio-template-convert.py --version

# List all GPIO symbols with their numeric ID
python3 gpio-template-convert.py list

# Encode human JSON → Tasmota JSON (stdout)
python3 gpio-template-convert.py encode examples/mcp23017_buttons_relays.json

# Encode to file
python3 gpio-template-convert.py encode my_template.json --output tasmota_template.json

# Decode Tasmota JSON string → human JSON (stdout)
python3 gpio-template-convert.py decode '{"NAME":"...","GPIO":[...],"FLAG":0,"BASE":1}'

# Decode Tasmota JSON file → human JSON file
python3 gpio-template-convert.py decode tasmota_template.json --output my_template.json

# Roundtrip check (encode + decode, print both)
python3 gpio-template-convert.py roundtrip my_template.json
```

## Human JSON format

```json
{
  "_comment": "optional ignored fields start with _",
  "name": "My Board",
  "base": 1,
  "flag": 0,
  "gpios": [
    "NONE",
    "KEY1",
    "KEY1",
    "KEY1:2",
    "LED1_INV_OPENDRAIN",
    "LED1_INV_OPENDRAIN:1",
    "REL1",
    "NONE:1"
  ]
}
```

**GPIO name forms** (all equivalent for the same GPIO):
- `GPIO_LED1_INV_OPENDRAIN` — full canonical name
- `LED1_INV_OPENDRAIN` — short name (GPIO_ prefix stripped)
- `GPIO_OLED_RESET` — backward-compat alias (resolved via `#define`)

**Pin index**:
- Omit → auto-incremented per GPIO type (e.g. three `KEY1` → indices 0, 1, 2)
- `KEY1:5` → explicit index 5
- `NONE` → always encodes as 0; `NONE:1` → encodes as 1 (Tasmota "pin present" marker)

### MCP23017 template (add `topology` key)

```json
{
  "name": "MCP23017 A=Buttons, B=relays/leds",
  "base": 1,
  "topology": [16, 0, 0, 0],
  "gpios": [
    "KEY1", "KEY1", "KEY1", "KEY1",
    "KEY1", "KEY1", "KEY1", "KEY1",
    "LED1_INV_OPENDRAIN", "REL1:4",
    "LED1_INV_OPENDRAIN:1", "REL1:5",
    "LED1_INV_OPENDRAIN:2", "REL1:6",
    "LED1_INV_OPENDRAIN:3", "REL1:7"
  ]
}
```

## Examples

See the [examples/](examples/) directory:

| File | Description |
|------|-------------|
| `examples/swimpool_v2_module.json` | SwimPool-V2 ESP32 main module (36 GPIOs) |
| `examples/mcp23017_buttons_relays.json` | MCP23017: 8 buttons + 4 relays + 4 open-drain LEDs |

## Why this tool?

Tasmota template values are opaque numbers. When a new GPIO is inserted into
`UserSelectablePins`, all existing numeric templates silently break. With this tool,
templates are stored symbolically and regenerated — no manual number hunting needed.
