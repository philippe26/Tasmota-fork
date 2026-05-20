#!/usr/bin/env python3
"""
gpio-template-convert.py — Tasmota GPIO template converter

Converts between human-readable JSON (with symbolic GPIO names) and the
compact Tasmota JSON template format used in "UI > Other > Template".

Encoding: template_value = (gpio_enum_index << 5) | pin_index
  gpio_enum_index : position of the GPIO in UserSelectablePins enum
  pin_index       : 0-based instance index (LED1=0, LED2=1 …)

Locates tasmota_template.h and tasmota_version.h automatically by walking
up from the script location to find the tasmota/include/ directory.

Commands:
  encode  <input.json>  [--output out.json]   Human JSON → Tasmota JSON
  decode  <input>       [--output out.json]   Tasmota JSON (file or string) → human JSON
  roundtrip <input.json>                      Encode + decode, show both
  list                                        Print GPIO symbol table

Examples:
  python3 gpio-template-convert.py encode swimpool.json
  python3 gpio-template-convert.py decode '{"NAME":"...","GPIO":[...],"FLAG":0,"BASE":1}'
  python3 gpio-template-convert.py decode template.json --output human.json
  python3 gpio-template-convert.py list
  python3 gpio-template-convert.py --version
"""

import argparse
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Auto-locate tasmota include directory
# ---------------------------------------------------------------------------

def find_include_dir(start: Path) -> Path:
    """Walk up from start until we find tasmota/include/tasmota_template.h."""
    for parent in [start, *start.parents]:
        candidate = parent / "tasmota" / "include" / "tasmota_template.h"
        if candidate.exists():
            return candidate.parent
    raise FileNotFoundError(
        "Cannot find tasmota/include/tasmota_template.h — "
        "run this script from within the Tasmota source tree."
    )


SCRIPT_DIR = Path(__file__).resolve().parent
INCLUDE_DIR = find_include_dir(SCRIPT_DIR)
TEMPLATE_H  = INCLUDE_DIR / "tasmota_template.h"
VERSION_H   = INCLUDE_DIR / "tasmota_version.h"
EN_GB_H     = INCLUDE_DIR.parent / "language" / "en_GB.h"


# ---------------------------------------------------------------------------
# Version parsing
# ---------------------------------------------------------------------------

def parse_tasmota_version() -> str:
    """Return human-readable version string from tasmota_version.h."""
    text = VERSION_H.read_text(encoding="utf-8")

    m_ver   = re.search(r"TASMOTA_VERSION\s*=\s*0x([0-9A-Fa-f]{8})", text)
    m_build = re.search(r"#define\s+TASMOTA_BUILD\s+0x([0-9A-Fa-f]+)", text)

    if not m_ver:
        return "unknown"

    raw = int(m_ver.group(1), 16)
    major  = (raw >> 24) & 0xFF
    minor  = (raw >> 16) & 0xFF
    patch  = (raw >>  8) & 0xFF
    build  = raw & 0xFF

    if m_build:
        build = int(m_build.group(1), 16)

    return f"{major}.{minor}.{patch}.{build:02X}"


TOOL_VERSION = "1.1"


# ---------------------------------------------------------------------------
# Parse sensor labels from kSensorNames[] + en_GB.h
# ---------------------------------------------------------------------------

def parse_defines() -> dict[str, str]:
    defines: dict[str, str] = {}
    if EN_GB_H.exists():
        for m in re.finditer(r'#define\s+(D_\w+)\s+"([^"]*)"',
                             EN_GB_H.read_text(encoding="utf-8")):
            defines[m.group(1)] = m.group(2)
    return defines


def parse_sensor_names(defines: dict[str, str]) -> list[str]:
    """Return list of UI label strings indexed by GPIO enum position."""
    text = TEMPLATE_H.read_text(encoding="utf-8")
    m = re.search(r"const char kSensorNames\[\] PROGMEM\s*=\s*(.+?);",
                  text, re.DOTALL)
    if not m:
        return []
    body = m.group(1)
    body = re.sub(r"^#[^\n]*\n", "", body, flags=re.MULTILINE)
    body = re.sub(r"//[^\n]*", "", body)
    frags: list[str] = []
    for tok in re.findall(r'D_\w+|"[^"]*"', body):
        frags.append(tok[1:-1] if tok.startswith('"') else defines.get(tok, tok))
    return [s for s in "".join(frags).split("|") if s]


# ---------------------------------------------------------------------------
# Parse UserSelectablePins enum from tasmota_template.h
# ---------------------------------------------------------------------------

def parse_gpio_enum() -> dict[str, int]:
    """Return {GPIO_NAME: numeric_id} ordered by enum position."""
    text = TEMPLATE_H.read_text(encoding="utf-8")

    m = re.search(r"enum\s+UserSelectablePins\s*\{(.+?)\};", text, re.DOTALL)
    if not m:
        raise ValueError(f"Cannot find UserSelectablePins enum in {TEMPLATE_H}")

    body = m.group(1)
    body = re.sub(r"//[^\n]*", "", body)           # strip // comments
    body = re.sub(r"^#[^\n]*", "", body, flags=re.MULTILINE)  # strip #define lines

    tokens = re.findall(r"\b(GPIO_\w+)\b", body)
    return {name: idx for idx, name in enumerate(tokens)}


def build_symbol_table(gpio_map: dict[str, int]) -> dict[str, int]:
    """Add #define aliases and short names (without GPIO_ prefix)."""
    text = TEMPLATE_H.read_text(encoding="utf-8")
    extras: dict[str, int] = {}

    for m in re.finditer(r"#define\s+(GPIO_\w+)\s+(GPIO_\w+)", text):
        alias, target = m.group(1), m.group(2)
        if target in gpio_map and alias not in gpio_map:
            extras[alias] = gpio_map[target]

    full = {**gpio_map, **extras}
    shorts: dict[str, int] = {}
    for name, idx in full.items():
        short = name.removeprefix("GPIO_")
        if short not in full and short not in shorts:
            shorts[short] = idx

    return {**full, **shorts}


def build_reverse_map(gpio_map: dict[str, int]) -> dict[int, str]:
    """Return {numeric_id: canonical_GPIO_name}."""
    rev: dict[int, str] = {}
    for name, idx in gpio_map.items():
        if name.startswith("GPIO_") and idx not in rev:
            rev[idx] = name
    return rev


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------

def encode_pin(gpio_id: int, pin_index: int) -> int:
    return (gpio_id << 5) | (pin_index & 0x1F)


def decode_pin(value: int) -> tuple[int, int]:
    return value >> 5, value & 0x1F


# ---------------------------------------------------------------------------
# Encode: human JSON → Tasmota JSON
# ---------------------------------------------------------------------------

def encode_template(tpl: dict, sym: dict[str, int]) -> dict:
    name     = tpl.get("name", "Custom")
    base     = tpl.get("base", 1)
    flag     = tpl.get("flag", 0)
    topology = tpl.get("topology")

    counters: dict[int, int] = {}
    encoded:  list[int]      = []

    for entry in tpl.get("gpios", []):
        if isinstance(entry, int):
            encoded.append(entry)
            continue

        s = str(entry).strip()

        # Explicit pin index: "LED1_INV_OPENDRAIN:2"
        if ":" in s:
            gpio_name, pin_str = s.rsplit(":", 1)
            gpio_name = gpio_name.strip()
            pin_index = int(pin_str.strip())
        else:
            gpio_name = s
            pin_index = None

        gpio_id = sym.get(gpio_name) if gpio_name in sym else sym.get("GPIO_" + gpio_name)
        if gpio_id is None:
            raise ValueError(f"Unknown GPIO symbol: {gpio_name!r}")

        # NONE (id=0) without explicit index → always 0
        if gpio_id == 0 and pin_index is None:
            encoded.append(0)
            continue

        if pin_index is None:
            pin_index = counters.get(gpio_id, 0)
            counters[gpio_id] = pin_index + 1

        encoded.append(encode_pin(gpio_id, pin_index))

    result = {"NAME": name, "GPIO": encoded, "FLAG": flag, "BASE": base}
    if topology is not None:
        result["TOPOLOGY"] = topology
    return result


# ---------------------------------------------------------------------------
# Decode: Tasmota JSON → human JSON
# ---------------------------------------------------------------------------

def decode_template(tasmota: dict, rev: dict[int, str],
                    sensor_names: list[str] | None = None) -> dict:
    name     = tasmota.get("NAME", "Custom")
    base     = tasmota.get("BASE", 1)
    flag     = tasmota.get("FLAG", 0)
    topology = tasmota.get("TOPOLOGY")

    counters: dict[int, int] = {}
    gpios:    list[str]      = []
    labels:   list[str]      = []

    for value in tasmota.get("GPIO", []):
        if value == 0:
            gpios.append("NONE")
            labels.append("None")
            continue
        gpio_id, pin_index = decode_pin(value)
        gpio_name = rev.get(gpio_id, f"UNKNOWN_{gpio_id}")
        expected = counters.get(gpio_id, 0)
        if pin_index != expected or pin_index > 0:
            gpios.append(f"{gpio_name}:{pin_index}")
        else:
            gpios.append(gpio_name)
        label = (sensor_names[gpio_id]
                 if sensor_names and gpio_id < len(sensor_names) and sensor_names[gpio_id]
                 else gpio_name.removeprefix("GPIO_"))
        labels.append(label)
        counters[gpio_id] = pin_index + 1

    result = {"name": name, "base": base, "flag": flag, "gpios": gpios}
    if topology is not None:
        result["topology"] = topology
    if sensor_names is not None:
        result["_labels"] = labels
    return result


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_human_template(path: Path) -> dict:
    """Load human JSON template, stripping _comment fields."""
    data = load_json_file(path)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def write_output(data: dict, output: Path | None, compact: bool = False) -> None:
    text = (json.dumps(data, separators=(",", ":"))
            if compact
            else json.dumps(data, indent=2, ensure_ascii=False))
    if output:
        output.write_text(text + "\n", encoding="utf-8")
        print(f"Written to {output}", file=sys.stderr)
    else:
        print(text)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_encode(args):
    gpio_map = parse_gpio_enum()
    sym      = build_symbol_table(gpio_map)
    tpl      = load_human_template(args.input)
    result   = encode_template(tpl, sym)
    write_output(result, args.output, compact=True)


def cmd_decode(args):
    gpio_map = parse_gpio_enum()
    rev      = build_reverse_map(gpio_map)
    defines  = parse_defines()
    sensors  = parse_sensor_names(defines)

    raw = str(args.input)
    path = Path(raw)
    data = load_json_file(path) if path.exists() else json.loads(raw)

    human = decode_template(data, rev, sensor_names=sensors)
    write_output(human, args.output, compact=False)


def cmd_roundtrip(args):
    gpio_map = parse_gpio_enum()
    sym      = build_symbol_table(gpio_map)
    rev      = build_reverse_map(gpio_map)
    defines  = parse_defines()
    sensors  = parse_sensor_names(defines)
    tpl      = load_human_template(args.input)

    encoded = encode_template(tpl, sym)
    decoded = decode_template(encoded, rev, sensor_names=sensors)

    print("=== Tasmota JSON ===")
    print(json.dumps(encoded, separators=(",", ":")))
    print("\n=== Decoded human JSON ===")
    print(json.dumps(decoded, indent=2, ensure_ascii=False))


def cmd_list(args):
    gpio_map = parse_gpio_enum()
    defines  = parse_defines()
    sensors  = parse_sensor_names(defines)
    print(f"{'ID':>5}  {'GPIO name':<40}  UI label")
    print("-" * 72)
    for name, idx in gpio_map.items():
        label = sensors[idx] if idx < len(sensors) else ""
        print(f"{idx:>5}  {name:<40}  {label}")
    print(f"\nTotal: {len(gpio_map)} GPIO symbols  (tasmota {parse_tasmota_version()})")


def cmd_version(args):
    print(f"gpio-template-convert {TOOL_VERSION}  (Tasmota {parse_tasmota_version()})")
    print(f"Header: {TEMPLATE_H}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Tasmota GPIO template converter — symbolic ↔ numeric",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--version", action="store_true",
        help="Print tool and Tasmota version then exit",
    )

    sub = parser.add_subparsers(dest="cmd")

    p_enc = sub.add_parser("encode", help="Human JSON → compact Tasmota JSON")
    p_enc.add_argument("input",  type=Path, help="Input human template (.json)")
    p_enc.add_argument("--output", "-o", type=Path, default=None,
                       metavar="FILE", help="Write output to file (default: stdout)")
    p_enc.set_defaults(func=cmd_encode)

    p_dec = sub.add_parser("decode", help="Tasmota JSON → human JSON")
    p_dec.add_argument("input", help="Tasmota JSON file path or inline JSON string")
    p_dec.add_argument("--output", "-o", type=Path, default=None,
                       metavar="FILE", help="Write output to file (default: stdout)")
    p_dec.set_defaults(func=cmd_decode)

    p_rt = sub.add_parser("roundtrip", help="Encode then decode, print both forms")
    p_rt.add_argument("input", type=Path, help="Input human template (.json)")
    p_rt.set_defaults(func=cmd_roundtrip)

    p_ls = sub.add_parser("list", help="Print GPIO symbol table")
    p_ls.set_defaults(func=cmd_list)

    args = parser.parse_args()

    if args.version:
        cmd_version(args)
        return

    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
