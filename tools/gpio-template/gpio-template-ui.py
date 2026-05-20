#!/usr/bin/env python3
"""
gpio-template-ui.py — Graphical Tasmota GPIO template editor

Mimics the Tasmota "Configuration > Template" web UI:
  - One row per GPIO slot, function dropdown + optional index dropdown
  - Index dropdown hidden when only one instance is possible
  - Hardware presets with GPIOs in physical ascending order
  - Topology mode (MCP23017/PCF8574): multiple tables, one per device
  - Opens human JSON or encoded Tasmota JSON
  - Saves as human JSON; "View" button encodes and shows Tasmota JSON

Usage:
  python3 gpio-template-ui.py [OPTIONS]

  Without options: launches the GUI (in background, console is freed)

Options:
  --input FILE       Open template file on startup
  --based-on NAME    Start from hardware preset (ESP32, ESP32-S3, …)
  --version          Print version string and exit (no display required)
  --help             Print this help and exit
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# ---------------------------------------------------------------------------
# Re-launch in background if we are the foreground process
# (so the terminal is freed immediately)
# ---------------------------------------------------------------------------

def _relaunch_background():
    """If stdin is a tty (interactive terminal), re-exec ourselves detached."""
    if os.name == "nt":
        return   # Windows: skip
    if not sys.stdin.isatty():
        return   # already detached or piped
    if os.environ.get("_TASMOTA_UI_BG"):
        return   # already re-launched
    env = os.environ.copy()
    env["_TASMOTA_UI_BG"] = "1"
    subprocess.Popen(
        [sys.executable] + sys.argv,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    sys.exit(0)


# ---------------------------------------------------------------------------
# Locate sibling convert script and tasmota include dir
# ---------------------------------------------------------------------------

SCRIPT_DIR   = Path(__file__).resolve().parent
CONVERT      = SCRIPT_DIR / "gpio-template-convert.py"
PYTHON       = sys.executable
TOOL_VERSION = "1.4"


def _run_convert(*args: str) -> str:
    result = subprocess.run(
        [PYTHON, str(CONVERT), *args],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def find_include_dir(start: Path) -> Path:
    for parent in [start, *start.parents]:
        candidate = parent / "tasmota" / "include" / "tasmota_template.h"
        if candidate.exists():
            return candidate.parent
    raise FileNotFoundError("Cannot find tasmota/include/tasmota_template.h")


INCLUDE_DIR = find_include_dir(SCRIPT_DIR)
TEMPLATE_H  = INCLUDE_DIR / "tasmota_template.h"
EN_GB_H     = INCLUDE_DIR.parent / "language" / "en_GB.h"
VERSION_H   = INCLUDE_DIR / "tasmota_version.h"


# ---------------------------------------------------------------------------
# Tasmota version
# ---------------------------------------------------------------------------

def tasmota_version() -> str:
    text = VERSION_H.read_text(encoding="utf-8")
    m_ver   = re.search(r"TASMOTA_VERSION\s*=\s*0x([0-9A-Fa-f]{8})", text)
    m_build = re.search(r"#define\s+TASMOTA_BUILD\s+0x([0-9A-Fa-f]+)", text)
    if not m_ver:
        return "?"
    raw = int(m_ver.group(1), 16)
    major, minor, patch = (raw >> 24) & 0xFF, (raw >> 16) & 0xFF, (raw >> 8) & 0xFF
    build = int(m_build.group(1), 16) if m_build else raw & 0xFF
    return f"{major}.{minor}.{patch}.{build:02X}"


TASMOTA_VERSION = tasmota_version()


# ---------------------------------------------------------------------------
# Hardware presets
#
# Each preset describes a list of (physical_gpio, type) tuples in ASCENDING
# physical GPIO order.
#
# type:
#   "IO"  — normal GPIO
#   "AO"  — ADC-capable
#   "IA"  — input-only (no output)
#   "TX"  — UART TX (usable but critical)
#   "RX"  — UART RX (usable but critical)
#   "FL"  — flash SPI pin (shown greyed/disabled)
#   "WARN"— usable but critical (PSRAM, strapping, etc.)
#
# slot_index: position in the Tasmota template array (GPIO[] in JSON).
# For ESP32 this is NOT the same as the physical GPIO number.
# ---------------------------------------------------------------------------

class SlotDef:
    """One configurable GPIO slot."""
    __slots__ = ("phy", "slot_idx", "slot_type", "label")

    def __init__(self, phy: int, slot_idx: int, slot_type: str, label: str = ""):
        self.phy       = phy
        self.slot_idx  = slot_idx
        self.slot_type = slot_type
        self.label     = label or f"GPIO{phy:02d}"


class HardwarePreset:
    def __init__(self, name: str, description: str, slots: list[SlotDef]):
        self.name        = name
        self.description = description
        self.all_slots   = slots   # all, including FL

    @property
    def visible_slots(self) -> list[SlotDef]:
        """All slots except flash pins."""
        return [s for s in self.all_slots if s.slot_type != "FL"]

    @property
    def total_template_slots(self) -> int:
        """Size of the GPIO[] array in the Tasmota template."""
        return max((s.slot_idx for s in self.all_slots), default=0) + 1


# ---------------------------------------------------------------------------
# ESP32 (WROOM-32 / DevKit)
# Physical GPIOs 0-27, 32-39  (28,29,30,31 don't exist)
# Template slots != physical order — mapping from tasmota_template.h
# Critical: 6-11 (SPI flash), 16-17 (PSRAM on WROOM)
# ---------------------------------------------------------------------------

# Physical GPIO → template slot index
_ESP32_PHY_TO_SLOT: dict[int, int] = {
    0: 0,  1: 1,  2: 2,  3: 3,  4: 4,  5: 5,
    9: 6,  10: 7,
    12: 8, 13: 9, 14: 10, 15: 11,
    16: 12, 17: 13, 18: 14, 19: 15,
    20: 16, 21: 17, 22: 18, 23: 19,
    24: 20, 25: 21, 26: 22, 27: 23,
    6: 24, 7: 25, 8: 26, 11: 27,
    32: 28, 33: 29, 34: 30, 35: 31,
    36: 32, 37: 33, 38: 34, 39: 35,
}

def _esp32_slots() -> list[SlotDef]:
    slots = []
    # Physical GPIOs in ascending order: 0-27 (skip 28-31), 32-39
    phys = list(range(0, 28)) + list(range(32, 40))
    for phy in phys:
        slot_idx = _ESP32_PHY_TO_SLOT[phy]
        if phy in range(6, 12):
            t = "FL"            # SPI flash — disabled
        elif phy in (16, 17):
            t = "WARN"          # PSRAM on WROOM — show but warn
        elif phy in (34, 35, 36, 39):
            t = "IA"            # input only
        elif phy in (32, 33, 37, 38):
            t = "AO"            # ADC capable
        elif phy in (1,):
            t = "TX"
        elif phy in (3,):
            t = "RX"
        else:
            t = "IO"
        slots.append(SlotDef(phy, slot_idx, t))
    return slots


def _flat_slots(phys: list[int],
                flash_range: range | list = (),
                warn: list[int] = (),
                adc: list[int] = (),
                input_only: list[int] = ()) -> list[SlotDef]:
    """Build slots where slot_idx == physical GPIO (simple chips)."""
    slots = []
    for phy in phys:
        if phy in flash_range:
            t = "FL"
        elif phy in warn:
            t = "WARN"
        elif phy in input_only:
            t = "IA"
        elif phy in adc:
            t = "AO"
        else:
            t = "IO"
        slots.append(SlotDef(phy, phy, t))
    return slots


HARDWARE_PRESETS: dict[str, HardwarePreset] = {}


def _reg(name: str, desc: str, slots: list[SlotDef]):
    HARDWARE_PRESETS[name] = HardwarePreset(name, desc, slots)


# --- ESP32 DevKit (WROOM-32) ---
_reg("ESP32-DevKit",
     "ESP32 WROOM-32 DevKit — 36 GPIOs (0-27, 32-39); flash=6-11; PSRAM warn=16,17",
     _esp32_slots())

# --- ESP32-S3 ---
# GPIOs 0-21, 33-48. 22-25 don't exist, 26-32 flash, 33-37 PSRAM
_s3_phys = list(range(0, 22)) + list(range(33, 49))
_reg("ESP32-S3",
     "ESP32-S3 — 38 user GPIOs; flash=26-32; PSRAM warn=33-37",
     _flat_slots(_s3_phys,
                 flash_range=range(26, 33),
                 warn=list(range(33, 38)),
                 adc=list(range(1, 11))))

# --- ESP32-S2 ---
_s2_phys = list(range(0, 22)) + list(range(33, 47))
_reg("ESP32-S2",
     "ESP32-S2 — 36 user GPIOs; flash=26-32",
     _flat_slots(_s2_phys,
                 flash_range=range(26, 33),
                 adc=list(range(1, 11))))

# --- ESP32-C3 ---
_reg("ESP32-C3",
     "ESP32-C3 — 22 GPIOs; flash=11-17",
     _flat_slots(list(range(0, 22)),
                 flash_range=range(11, 18),
                 adc=list(range(0, 6))))

# --- ESP32-C6 ---
_reg("ESP32-C6",
     "ESP32-C6 — 31 GPIOs; flash=24-30",
     _flat_slots(list(range(0, 31)),
                 flash_range=range(24, 31),
                 adc=list(range(0, 7))))

# --- ESP8266 / Wemos D1 Mini ---
# GPIO 6-8,11 = flash; GPIO 9,10 = flash on QIO mode
_reg("ESP8266",
     "ESP8266 / Wemos D1 Mini — 17 GPIOs; flash=6-8,11; ADC=17",
     _flat_slots([0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17],
                 flash_range=[6, 7, 8, 11],
                 warn=[9, 10],
                 adc=[17]))

# --- Generic flat layouts (for I2C expanders) ---
_reg("Generic-16",
     "16 flat slots — I2C expander (MCP23017, PCF8574…)",
     [SlotDef(i, i, "IO") for i in range(16)])

_reg("Generic-8",
     "8 flat slots — I2C expander half-port",
     [SlotDef(i, i, "IO") for i in range(8)])


# ---------------------------------------------------------------------------
# GPIO data parsing
# ---------------------------------------------------------------------------

def parse_defines(path: Path) -> dict[str, str]:
    defines: dict[str, str] = {}
    for m in re.finditer(r'#define\s+(D_\w+)\s+"([^"]*)"',
                         path.read_text(encoding="utf-8")):
        defines[m.group(1)] = m.group(2)
    return defines


def parse_sensor_names(defines: dict[str, str]) -> list[str]:
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


def parse_gpio_enum() -> dict[str, int]:
    text = TEMPLATE_H.read_text(encoding="utf-8")
    m = re.search(r"enum\s+UserSelectablePins\s*\{(.+?)\};", text, re.DOTALL)
    body = re.sub(r"//[^\n]*", "", m.group(1))
    body = re.sub(r"^#[^\n]*", "", body, flags=re.MULTILINE)
    tokens = re.findall(r"\b(GPIO_\w+)\b", body)
    return {name: idx for idx, name in enumerate(tokens)}


def parse_nice_list(gpio_map: dict[str, int]) -> list[tuple[int, int]]:
    text = TEMPLATE_H.read_text(encoding="utf-8")
    m = re.search(r"const uint16_t kGpioNiceList\[\] PROGMEM\s*=\s*\{(.+?)\};",
                  text, re.DOTALL)
    body = re.sub(r"^#[^\n]*\n", "", m.group(1), flags=re.MULTILINE)
    body = re.sub(r"//[^\n]*", "", body)
    MAX = {
        "MAX_KEYS": 32, "MAX_SWITCHES": 32, "MAX_RELAYS": 32,
        "MAX_LEDS": 32, "MAX_COUNTERS": 4, "MAX_PWMS": 5,
        "MAX_ROTARIES": 2, "MAX_OPTIONS_A": 9, "MAX_OPTIONS_E": 1,
        "MAX_I2C": 2, "MAX_SPI": 2, "MAX_I2S": 4, "MAX_SR04": 3,
        "MAX_WEBCAM_DATA": 8, "MAX_WEBCAM_HSD": 3,
        "MAX_A4988": 4, "MAX_A4988_MSS": 3,
        "MAX_WINDMETER": 4, "MAX_TELEINFO": 2,
        "MAX_MCP23XXX": 6, "MAX_DSB": 4,
        "MAX_RMT": 8, "MAX_IRSEND": 16,
        "MAX_ADCS": 8, "VL53LXX_MAX_SENSORS": 8,
        "MAX_MAX31855S": 6, "MAX_MAX31865S": 6,
        "MAX_SM2135_DAT": 10, "MAX_SM2335_DAT": 16, "MAX_BP1658CJ_DAT": 16,
        "MAX_FLOWRATEMETER": 2, "MAX_DINGTIAN_SHIFT": 4, "MAX_MAGIC_SWITCH_MODES": 2,
        "MAX_BL0906_RX": 6, "MAX_BL0942_RX": 8, "MAX_CSE7761": 2,
        "MAX_TWAI": 2, "MAX_GPS_RX": 3, "MAX_MKSKYBLU_IF": 8,
    }
    result: list[tuple[int, int]] = []
    seen: set[int] = set()
    pat = re.compile(r'AGPIO\((GPIO_\w+)\)(?:\s*\+\s*AGMAX\((\w+|\d+)\))?|(GPIO_NONE)\b')
    for m2 in pat.finditer(body):
        if m2.group(3):
            gid = 0
        else:
            gid = gpio_map.get(m2.group(1))
            if gid is None:
                continue
        if gid in seen:
            continue
        seen.add(gid)
        tok = m2.group(2) if not m2.group(3) else None
        max_inst = (1 if tok is None else
                    int(tok) if tok.isdigit() else
                    MAX.get(tok, 1))
        result.append((gid, max_inst))
    return result


def build_dropdown_options(nice_list: list[tuple[int, int]],
                           sensor_names: list[str],
                           gpio_map: dict[str, int]) -> list[tuple[int, str, int]]:
    rev = {v: k for k, v in gpio_map.items() if k.startswith("GPIO_")}
    result: list[tuple[int, str, int]] = []
    for gid, mx in nice_list:
        if gid < len(sensor_names) and sensor_names[gid]:
            label = sensor_names[gid]
        else:
            raw = rev.get(gid, f"GPIO_{gid}")
            label = raw.removeprefix("GPIO_").replace("_", " ").title()
        result.append((gid << 5, label, mx))
    return result


def build_symbol_table(gpio_map: dict[str, int]) -> dict[str, int]:
    text = TEMPLATE_H.read_text(encoding="utf-8")
    extras: dict[str, int] = {}
    for m in re.finditer(r"#define\s+(GPIO_\w+)\s+(GPIO_\w+)", text):
        alias, tgt = m.group(1), m.group(2)
        if tgt in gpio_map and alias not in gpio_map:
            extras[alias] = gpio_map[tgt]
    full = {**gpio_map, **extras}
    shorts = {k.removeprefix("GPIO_"): v for k, v in full.items()
              if k.removeprefix("GPIO_") not in full}
    return {**full, **shorts}


# ---------------------------------------------------------------------------
# MCP23x allowed GPIO functions
# (from xdrv_67_mcp23xxx.ino — only these make sense on an I/O expander)
# ---------------------------------------------------------------------------

MCP23X_ALLOWED_GPIOS = {
    "GPIO_NONE",
    "GPIO_KEY1", "GPIO_KEY1_NP", "GPIO_KEY1_PD",
    "GPIO_KEY1_INV", "GPIO_KEY1_INV_NP", "GPIO_KEY1_INV_PD",
    "GPIO_SWT1", "GPIO_SWT1_NP", "GPIO_SWT1_PD",
    "GPIO_REL1", "GPIO_REL1_INV",
    "GPIO_LED1", "GPIO_LED1_INV", "GPIO_LED1_INV_OPENDRAIN",
    "GPIO_LEDLNK", "GPIO_LEDLNK_INV",
    "GPIO_OUTPUT_HI", "GPIO_OUTPUT_LO",
}


def build_mcp23x_options(gpio_options: list[tuple[int, str, int]],
                         gpio_map: dict[str, int]) -> list[tuple[int, str, int]]:
    """Filter gpio_options to MCP23x-supported functions only."""
    allowed_ids = {gpio_map[g] for g in MCP23X_ALLOWED_GPIOS if g in gpio_map}
    allowed_ids.add(0)  # GPIO_NONE always allowed
    return [(enc, lbl, mx) for enc, lbl, mx in gpio_options
            if (enc >> 5) in allowed_ids]


# ---------------------------------------------------------------------------
# Encode / decode helpers
# ---------------------------------------------------------------------------

def decode_pin(value: int) -> tuple[int, int]:
    return value >> 5, value & 0x1F


def encode_pin(gpio_id: int, pin_index: int) -> int:
    return (gpio_id << 5) | (pin_index & 0x1F)


def encoded_list_to_symbolic(encoded: list[int],
                              rev_map: dict[int, str]) -> list[str]:
    counters: dict[int, int] = {}
    result: list[str] = []
    for val in encoded:
        if val == 0:
            result.append("NONE")
            continue
        gid, pin = decode_pin(val)
        if gid == 0:
            result.append(f"NONE:{pin}")
            continue
        name = rev_map.get(gid, f"UNKNOWN_{gid}")
        exp  = counters.get(gid, 0)
        result.append(f"{name}:{pin}" if pin != exp or pin > 0 else name)
        counters[gid] = pin + 1
    return result


def symbolic_list_to_encoded(syms: list[str],
                              sym_table: dict[str, int]) -> list[int]:
    counters: dict[int, int] = {}
    result: list[int] = []
    for entry in syms:
        s = str(entry).strip()
        if ":" in s:
            gname, pi = s.rsplit(":", 1)
            pin_index: int | None = int(pi.strip())
        else:
            gname, pin_index = s, None
        gid = (sym_table.get(gname) if gname in sym_table
               else sym_table.get("GPIO_" + gname, 0))
        if gid == 0 and pin_index is None:
            result.append(0)
            continue
        if pin_index is None:
            pin_index = counters.get(gid, 0)
            counters[gid] = pin_index + 1
        result.append(encode_pin(gid, pin_index))
    return result


# ---------------------------------------------------------------------------
# Colour scheme
# ---------------------------------------------------------------------------

C_BG       = "#2b2b2b"
C_PANEL    = "#3a3a3a"
C_ROW_ODD  = "#2b2b2b"
C_ROW_EVEN = "#313131"
C_FG       = "#e8e8e8"     # normal GPIO text (white)
C_FG_WARN  = "#ff6b6b"     # critical GPIO (red)
C_FG_FLASH = "#666666"     # flash pin (dim)
C_FG_DIM   = "#888888"
C_ACCENT   = "#1a73e8"
C_BTN_FG   = "#ffffff"
C_ENTRY_BG = "#ffffff"     # dropdown background (white)
C_ENTRY_FG = "#000000"     # dropdown text (black)
C_SEL      = "#1a73e8"
C_STATUS   = "#1f1f1f"
C_BORDER   = "#555555"
C_TOPO_HDR = "#404040"


# ---------------------------------------------------------------------------
# SlotRow — one GPIO row widget
# ---------------------------------------------------------------------------

class SlotRow:
    def __init__(self, parent: tk.Widget, row: int,
                 slot: SlotDef,
                 gpio_options: list[tuple[int, str, int]],
                 combo_labels: list[str],
                 on_change):
        self._slot       = slot
        self._gpio_options  = gpio_options
        self._opt_by_label: dict[str, tuple[int, int]] = {
            lbl: (enc, mx) for enc, lbl, mx in gpio_options
        }
        self._on_change  = on_change

        bg = C_ROW_ODD if row % 2 == 0 else C_ROW_EVEN

        if slot.slot_type == "FL":
            lbl_color = C_FG_FLASH
        elif slot.slot_type == "WARN":
            lbl_color = C_FG_WARN
        else:
            lbl_color = C_FG

        # GPIO label
        self._lbl = tk.Label(parent, text=slot.label, bg=bg, fg=lbl_color,
                             font=("Courier", 9, "bold"), width=9, anchor=tk.E)
        self._lbl.grid(row=row, column=0, sticky=tk.EW, padx=(4, 2), pady=1)

        # Function combobox  (disabled for flash pins)
        self._func_var = tk.StringVar(value="None")
        self._func_cb  = ttk.Combobox(
            parent, textvariable=self._func_var,
            values=combo_labels,
            state="disabled" if slot.slot_type == "FL" else "readonly",
            width=28,
        )
        self._func_cb.grid(row=row, column=1, sticky=tk.EW, padx=2, pady=1)
        self._func_cb.bind("<<ComboboxSelected>>", self._func_changed)

        # Index combobox (hidden by default, shown only when max_inst > 1)
        self._idx_var = tk.StringVar(value="1")
        self._idx_cb  = ttk.Combobox(
            parent, textvariable=self._idx_var,
            state="readonly", width=5,
        )
        self._idx_cb.grid(row=row, column=2, sticky=tk.W, padx=(2, 4), pady=1)
        self._idx_cb.bind("<<ComboboxSelected>>", lambda _: self._on_change())
        self._idx_cb.grid_remove()

    def _func_changed(self, _=None):
        label = self._func_var.get()
        info  = self._opt_by_label.get(label)
        if info:
            _, mx = info
            if mx > 1:
                self._idx_cb["values"] = [str(i + 1) for i in range(mx)]
                cur = int(self._idx_var.get() or "1")
                self._idx_var.set(str(min(cur, mx)))
                self._idx_cb.grid()
            else:
                self._idx_cb.grid_remove()
        self._on_change()

    def set_encoded(self, encoded: int):
        if encoded == 0:
            self._func_var.set("None")
            self._idx_cb.grid_remove()
            return
        gid, pin = decode_pin(encoded)
        enc_base = gid << 5
        label = next((lbl for enc, lbl, _ in self._gpio_options if enc == enc_base), "None")
        self._func_var.set(label)
        info = self._opt_by_label.get(label)
        if info:
            _, mx = info
            if mx > 1:
                self._idx_cb["values"] = [str(i + 1) for i in range(mx)]
                self._idx_var.set(str(min(pin + 1, mx)))
                self._idx_cb.grid()
                return
        self._idx_cb.grid_remove()

    def get_encoded(self) -> int:
        if self._slot.slot_type == "FL":
            return 0
        label = self._func_var.get()
        info  = self._opt_by_label.get(label)
        if not info:
            return 0
        enc_base, mx = info
        gid = enc_base >> 5
        if gid == 0:
            return 0
        pin = max(0, int(self._idx_var.get() or "1") - 1)
        return encode_pin(gid, pin)

    def destroy(self):
        self._lbl.destroy()
        self._func_cb.destroy()
        self._idx_cb.destroy()


# ---------------------------------------------------------------------------
# TopologyTable — LabelFrame for one device in multi-device mode
# ---------------------------------------------------------------------------

class TopologyTable(tk.LabelFrame):
    def __init__(self, parent, dev_label: str, offset: int, num_slots: int,
                 gpio_options, combo_labels, on_change, **kw):
        super().__init__(parent, text=dev_label,
                         bg=kw.pop("bg", C_BG), fg=kw.pop("fg", C_FG),
                         font=("Helvetica", 9, "bold"), **kw)
        self.offset    = offset
        self.num_slots = num_slots
        self._rows: list[SlotRow] = []

        # Header row
        for col, hdr in enumerate(["Pin", "Function", "Idx"]):
            tk.Label(self, text=hdr, bg=C_TOPO_HDR, fg=C_FG,
                     font=("Helvetica", 8, "bold"), padx=4).grid(
                row=0, column=col, sticky=tk.EW, padx=1)

        for i in range(num_slots):
            sd = SlotDef(i, i, "IO", f"Pin{i:02d}")
            r  = SlotRow(self, i + 1, sd, gpio_options, combo_labels, on_change)
            self._rows.append(r)

    def set_encoded_list(self, vals: list[int]):
        for i, r in enumerate(self._rows):
            r.set_encoded(vals[i] if i < len(vals) else 0)

    def get_encoded_list(self) -> list[int]:
        return [r.get_encoded() for r in self._rows]


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class TemplateEditor(tk.Tk):

    def __init__(self, initial_file: Path | None = None,
                 based_on: str | None = None):
        super().__init__()

        # Load GPIO metadata
        self._defines      = parse_defines(EN_GB_H)
        self._sensor_names = parse_sensor_names(self._defines)
        self._gpio_map     = parse_gpio_enum()
        self._nice_list    = parse_nice_list(self._gpio_map)
        self._rev_map      = {v: k for k, v in self._gpio_map.items()
                              if k.startswith("GPIO_")}
        self._sym_table    = build_symbol_table(self._gpio_map)
        self._gpio_options = build_dropdown_options(
            self._nice_list, self._sensor_names, self._gpio_map)
        self._combo_labels = [lbl for _, lbl, _ in self._gpio_options]
        self._mcp23x_options = build_mcp23x_options(self._gpio_options, self._gpio_map)
        self._mcp23x_labels  = [lbl for _, lbl, _ in self._mcp23x_options]

        # State
        self._filepath:    Path | None = None
        self._modified:    bool        = False
        self._preset:      HardwarePreset | None = None
        self._topology:    list[int] | None = None
        self._mode:        str = "preset"         # "preset" | "topology"
        self._is_mcp23x:   bool        = False    # topology mode uses MCP23x filter
        self._slot_rows:   list[SlotRow] = []
        self._topo_tables: list[TopologyTable] = []

        self._build_ui()
        self._apply_styles()

        if initial_file:
            self._open_file(initial_file)
        elif based_on:
            self._new_from_preset(self._find_preset(based_on))
        else:
            self._new_from_preset("ESP32-DevKit")

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------

    def _build_ui(self):
        self.title("Tasmota GPIO Template Editor")
        self.configure(bg=C_BG)
        self.resizable(True, True)
        self.minsize(540, 420)

        # ── Toolbar ──────────────────────────────────────────────────────────
        tb = tk.Frame(self, bg=C_PANEL, pady=5)
        tb.pack(fill=tk.X, side=tk.TOP)

        def tbtn(txt, cmd, accent=False):
            b = tk.Button(tb, text=txt, command=cmd,
                          bg=C_ACCENT if accent else C_BORDER,
                          fg=C_BTN_FG, relief=tk.FLAT,
                          font=("Helvetica", 9), padx=8, pady=2,
                          activebackground="#2a5fd8",
                          activeforeground=C_BTN_FG, cursor="hand2")
            b.pack(side=tk.LEFT, padx=3)
            return b

        tbtn("New…",        self._cmd_new)
        tbtn("New MCP23x…", self._cmd_new_multi)

        tk.Frame(tb, bg=C_BORDER, width=1, height=22).pack(
            side=tk.LEFT, padx=4, fill=tk.Y)

        tbtn("Open…",    self._cmd_open)
        tbtn("Save",     self._cmd_save)
        tbtn("Save As…", self._cmd_save_as)

        tk.Frame(tb, bg=C_BORDER, width=1, height=22).pack(
            side=tk.LEFT, padx=4, fill=tk.Y)

        tbtn("Check", self._cmd_check)
        tbtn("View",  self._cmd_view, accent=True)

        tk.Label(tb, text=f"Tasmota {TASMOTA_VERSION}",
                 bg=C_PANEL, fg=C_FG_DIM,
                 font=("Helvetica", 8)).pack(side=tk.RIGHT, padx=10)

        # ── Header fields ────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=C_PANEL, pady=6)
        hdr.pack(fill=tk.X, side=tk.TOP)

        def hlbl(t):
            return tk.Label(hdr, text=t, bg=C_PANEL, fg=C_FG,
                            font=("Helvetica", 9))

        def hentry(var, w=22):
            e = tk.Entry(hdr, textvariable=var, width=w,
                         bg=C_ENTRY_BG, fg=C_ENTRY_FG,
                         insertbackground=C_ENTRY_FG,
                         relief=tk.FLAT, bd=1, font=("Helvetica", 9))
            e.bind("<Key>", lambda _: self._mark_modified())
            return e

        hlbl("Name:").grid(row=0, column=0, padx=(8, 2), sticky=tk.W)
        self._name_var = tk.StringVar(value="Custom")
        hentry(self._name_var, 26).grid(row=0, column=1, padx=(0, 12), sticky=tk.W)

        hlbl("Base:").grid(row=0, column=2, padx=(0, 2), sticky=tk.W)
        self._base_var = tk.StringVar(value="1")
        hentry(self._base_var, 4).grid(row=0, column=3, padx=(0, 12), sticky=tk.W)

        hlbl("Flag:").grid(row=0, column=4, padx=(0, 2), sticky=tk.W)
        self._flag_var = tk.StringVar(value="0")
        hentry(self._flag_var, 4).grid(row=0, column=5, padx=(0, 4), sticky=tk.W)

        # Preset label (read-only info)
        self._preset_lbl_var = tk.StringVar(value="")
        tk.Label(hdr, textvariable=self._preset_lbl_var,
                 bg=C_PANEL, fg=C_FG_DIM,
                 font=("Helvetica", 8, "italic")).grid(
            row=0, column=6, padx=(12, 8), sticky=tk.W)

        # ── Status bar ───────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Ready")
        tk.Label(self, textvariable=self._status_var,
                 bg=C_STATUS, fg=C_FG_DIM, anchor=tk.W,
                 font=("Helvetica", 8), padx=8).pack(
            side=tk.BOTTOM, fill=tk.X)

        # ── Scrollable GPIO area ─────────────────────────────────────────────
        outer = tk.Frame(self, bg=C_BG)
        outer.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(outer, bg=C_BG, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL,
                            command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._inner = tk.Frame(self._canvas, bg=C_BG)
        self._cwin  = self._canvas.create_window(
            (0, 0), window=self._inner, anchor=tk.NW)

        self._inner.bind("<Configure>", self._on_frame_cfg)
        self._canvas.bind("<Configure>", self._on_canvas_cfg)
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)
        self._canvas.bind_all("<Button-4>",   self._on_wheel)
        self._canvas.bind_all("<Button-5>",   self._on_wheel)

    def _apply_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox",
                        fieldbackground=C_ENTRY_BG, foreground=C_ENTRY_FG,
                        background=C_ENTRY_BG, selectbackground=C_SEL,
                        selectforeground=C_ENTRY_BG, arrowcolor=C_ENTRY_FG)
        style.map("TCombobox",
                  fieldbackground=[("readonly", C_ENTRY_BG),
                                   ("disabled", C_PANEL)],
                  foreground=[("readonly", C_ENTRY_FG),
                              ("disabled", C_FG_DIM)])
        style.configure("TScrollbar",
                        background=C_PANEL, troughcolor=C_BG,
                        arrowcolor=C_FG_DIM)

    # -----------------------------------------------------------------------
    # Scroll helpers
    # -----------------------------------------------------------------------

    def _on_frame_cfg(self, _=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_cfg(self, event):
        self._canvas.itemconfig(self._cwin, width=event.width)

    def _on_wheel(self, event):
        if event.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            self._canvas.yview_scroll(-1 * (event.delta // 120), "units")

    # -----------------------------------------------------------------------
    # Grid builders
    # -----------------------------------------------------------------------

    def _clear_inner(self):
        for w in self._inner.winfo_children():
            w.destroy()
        self._slot_rows.clear()
        self._topo_tables.clear()

    def _build_preset_grid(self, preset: HardwarePreset,
                           encoded_map: dict[int, int] | None = None):
        """Single-table view: one row per slot, ordered by physical GPIO."""
        self._clear_inner()
        self._preset   = preset
        self._topology = None
        self._mode     = "preset"
        self._preset_lbl_var.set(preset.description)

        # Column headers
        for col, txt in enumerate(["GPIO", "Function", "Idx"]):
            tk.Label(self._inner, text=txt, bg=C_PANEL, fg=C_FG,
                     font=("Helvetica", 8, "bold"), padx=4).grid(
                row=0, column=col, sticky=tk.EW, padx=1, pady=(2, 4))

        for row_i, sd in enumerate(preset.all_slots):
            enc = (encoded_map.get(sd.slot_idx, 0)
                   if encoded_map else 0)
            r = SlotRow(self._inner, row_i + 1, sd,
                        self._gpio_options, self._combo_labels,
                        self._mark_modified)
            r.set_encoded(enc)
            self._slot_rows.append(r)

        self._canvas.yview_moveto(0)
        self._modified = False
        self._update_title()

    def _build_topology_grid(self, topology: list[int],
                             encoded_all: list[int] | None = None,
                             mcp23x: bool = False):
        """Multi-table view: one LabelFrame per device."""
        self._clear_inner()
        self._topology  = topology
        self._preset    = None
        self._mode      = "topology"
        self._is_mcp23x = mcp23x
        self._preset_lbl_var.set(
            f"MCP23x  topology={topology}" if mcp23x
            else f"Multi-device  topology={topology}"
        )

        opts   = self._mcp23x_options if mcp23x else self._gpio_options
        labels = self._mcp23x_labels  if mcp23x else self._combo_labels

        offset   = 0
        grid_row = 0
        for dev_i, sz in enumerate(topology):
            if sz == 0:
                offset += sz
                continue
            lbl = f"Device {dev_i}   (slots {offset} – {offset + sz - 1})"
            tbl = TopologyTable(
                self._inner, lbl, offset, sz,
                opts, labels,
                self._mark_modified,
                bg=C_BG, pady=4, padx=4,
            )
            tbl.grid(row=grid_row, column=0, sticky=tk.EW,
                     padx=8, pady=(4, 8))
            if encoded_all:
                tbl.set_encoded_list(encoded_all[offset:offset + sz])
            self._topo_tables.append(tbl)
            grid_row += 1
            offset   += sz

        self._canvas.yview_moveto(0)
        self._modified = False
        self._update_title()

    # -----------------------------------------------------------------------
    # Reading current state
    # -----------------------------------------------------------------------

    def _get_encoded_map(self) -> dict[int, int]:
        """Return {slot_idx: encoded_value} for preset mode."""
        result: dict[int, int] = {}
        if not self._preset:
            return result
        for row_i, sd in enumerate(self._preset.all_slots):
            if row_i < len(self._slot_rows):
                result[sd.slot_idx] = self._slot_rows[row_i].get_encoded()
        return result

    def _get_encoded_list(self) -> list[int]:
        """Return flat list of encoded values (indexed by slot_idx)."""
        if self._mode == "preset" and self._preset:
            enc_map = self._get_encoded_map()
            total   = self._preset.total_template_slots
            return [enc_map.get(i, 0) for i in range(total)]
        elif self._mode == "topology":
            result: list[int] = []
            for tbl in self._topo_tables:
                result.extend(tbl.get_encoded_list())
            return result
        return []

    def _template_to_dict(self) -> dict:
        encoded = self._get_encoded_list()
        syms    = encoded_list_to_symbolic(encoded, self._rev_map)
        labels  = self._encoded_list_to_labels(encoded)
        d: dict = {
            "name": self._name_var.get(),
            "base": self._safe_int(self._base_var.get(), 1),
            "flag": self._safe_int(self._flag_var.get(), 0),
            "gpios": syms,
        }
        if self._topology:
            d["topology"] = self._topology
        d["_labels"] = labels
        return d

    def _encoded_list_to_labels(self, encoded: list[int]) -> list[str]:
        """Return UI label for each encoded slot value."""
        result = []
        for val in encoded:
            if val == 0:
                result.append("None")
                continue
            gid, _ = decode_pin(val)
            label = (self._sensor_names[gid]
                     if gid < len(self._sensor_names) and self._sensor_names[gid]
                     else self._rev_map.get(gid, f"GPIO_{gid}").removeprefix("GPIO_"))
            result.append(label)
        return result

    @staticmethod
    def _safe_int(s: str, default: int) -> int:
        try:
            return int(s)
        except (ValueError, TypeError):
            return default

    # -----------------------------------------------------------------------
    # Load helpers
    # -----------------------------------------------------------------------

    def _load_human_dict(self, d: dict):
        self._name_var.set(d.get("name", "Custom"))
        self._base_var.set(str(d.get("base", 1)))
        self._flag_var.set(str(d.get("flag", 0)))
        syms    = d.get("gpios", [])
        encoded = symbolic_list_to_encoded(syms, self._sym_table)
        topo    = d.get("topology")
        if topo:
            self._build_topology_grid(topo, encoded, mcp23x=True)
        else:
            preset = self._best_preset_for(len(encoded))
            enc_map = {i: v for i, v in enumerate(encoded)}
            self._build_preset_grid(preset, enc_map)

    def _load_tasmota_dict(self, d: dict):
        self._name_var.set(d.get("NAME", "Custom"))
        self._base_var.set(str(d.get("BASE", 1)))
        self._flag_var.set(str(d.get("FLAG", 0)))
        encoded = d.get("GPIO", [])
        topo    = d.get("TOPOLOGY")
        if topo:
            self._build_topology_grid(topo, encoded, mcp23x=True)
        else:
            preset = self._best_preset_for(len(encoded))
            enc_map = {i: v for i, v in enumerate(encoded)}
            self._build_preset_grid(preset, enc_map)

    def _best_preset_for(self, n: int) -> HardwarePreset:
        best = HARDWARE_PRESETS["ESP32-DevKit"]
        best_diff = abs(best.total_template_slots - n)
        for p in HARDWARE_PRESETS.values():
            diff = abs(p.total_template_slots - n)
            if diff < best_diff:
                best, best_diff = p, diff
        return best

    def _find_preset(self, name: str) -> str:
        name_l = name.lower()
        for key in HARDWARE_PRESETS:
            if key.lower().startswith(name_l) or name_l in key.lower():
                return key
        return "ESP32-DevKit"

    # -----------------------------------------------------------------------
    # New template dialog (single device)
    # -----------------------------------------------------------------------

    def _cmd_new(self):
        if self._modified and not self._confirm_discard():
            return
        self._new_dialog(multi=False)

    def _cmd_new_multi(self):
        if self._modified and not self._confirm_discard():
            return
        self._new_dialog(multi=True)

    def _new_dialog(self, multi: bool):
        win = tk.Toplevel(self)
        win.configure(bg=C_BG)
        win.resizable(False, False)
        win.grab_set()

        if multi:
            # ── MCP23x dialog: topology only ─────────────────────────────────
            win.title("New MCP23x Template")

            tk.Label(win, text="MCP23x device topology",
                     bg=C_BG, fg=C_FG,
                     font=("Helvetica", 10, "bold")).grid(
                row=0, column=0, columnspan=2, padx=16, pady=(14, 2), sticky=tk.W)
            tk.Label(win,
                     text="Enter pin counts per device (comma-separated).\n"
                          "Use 0 to skip an I²C address.\n"
                          "e.g.  16,0,8  →  device0=16 pins (0x20), "
                          "device1=skipped (0x21), device2=8 pins (0x22)",
                     bg=C_BG, fg=C_FG_DIM, font=("Helvetica", 8),
                     wraplength=300, justify=tk.LEFT).grid(
                row=1, column=0, columnspan=2, padx=16, pady=(0, 6), sticky=tk.W)

            topo_var = tk.StringVar(value="16,8")
            te = tk.Entry(win, textvariable=topo_var, width=24,
                          bg=C_ENTRY_BG, fg=C_ENTRY_FG, relief=tk.FLAT,
                          font=("Helvetica", 10))
            te.grid(row=2, column=0, columnspan=2, padx=16, pady=(0, 8), sticky=tk.W)
            te.focus_set()
            te.select_range(0, tk.END)

            btn_row = 3

            def do_create():
                raw = topo_var.get().strip()
                try:
                    topo = [int(x.strip()) for x in raw.split(",") if x.strip()]
                except ValueError:
                    messagebox.showerror("Topology",
                                         "Enter comma-separated integers, e.g.  16,0,8",
                                         parent=win)
                    return
                if not any(s > 0 for s in topo):
                    messagebox.showerror("Topology",
                                         "At least one device must have a non-zero pin count.",
                                         parent=win)
                    return
                win.destroy()
                self._name_var.set("Custom")
                self._base_var.set("1")
                self._flag_var.set("0")
                self._filepath = None
                self._build_topology_grid(topo, mcp23x=True)
                self._status(f"New MCP23x template  topology={topo}")

            te.bind("<Return>", lambda _: do_create())

        else:
            # ── Single-device dialog: hardware preset ─────────────────────────
            win.title("New Template")

            tk.Label(win, text="Based on hardware:", bg=C_BG, fg=C_FG,
                     font=("Helvetica", 10)).grid(
                row=0, column=0, columnspan=2, padx=16, pady=(14, 4), sticky=tk.W)

            names = list(HARDWARE_PRESETS.keys())
            lb = tk.Listbox(win, listvariable=tk.StringVar(value=names),
                            height=min(len(names), 10), width=24,
                            bg=C_ENTRY_BG, fg=C_ENTRY_FG, selectmode=tk.SINGLE,
                            font=("Helvetica", 9), relief=tk.FLAT,
                            selectbackground=C_SEL, selectforeground=C_BTN_FG)
            lb.grid(row=1, column=0, columnspan=2, padx=16, pady=4)
            lb.selection_set(0)

            desc_var = tk.StringVar(value=HARDWARE_PRESETS[names[0]].description)
            tk.Label(win, textvariable=desc_var, bg=C_BG, fg=C_FG_DIM,
                     font=("Helvetica", 8), wraplength=260, justify=tk.LEFT).grid(
                row=2, column=0, columnspan=2, padx=16, pady=(0, 8), sticky=tk.W)

            def on_select(_=None):
                sel = lb.curselection()
                if sel:
                    desc_var.set(HARDWARE_PRESETS[names[sel[0]]].description)

            lb.bind("<<ListboxSelect>>", on_select)
            btn_row = 3

            def do_create():
                sel   = lb.curselection()
                pname = names[sel[0]] if sel else names[0]
                win.destroy()
                self._new_from_preset(pname)

            lb.bind("<Double-Button-1>", lambda _: do_create())

        # ── Buttons (shared) ─────────────────────────────────────────────────
        tk.Button(win, text="Create", command=do_create,
                  bg=C_ACCENT, fg=C_BTN_FG, relief=tk.FLAT,
                  font=("Helvetica", 9, "bold"), padx=12, pady=4,
                  cursor="hand2").grid(
            row=btn_row, column=0, pady=12, padx=8, sticky=tk.E)
        tk.Button(win, text="Cancel", command=win.destroy,
                  bg=C_BORDER, fg=C_BTN_FG, relief=tk.FLAT,
                  font=("Helvetica", 9), padx=12, pady=4,
                  cursor="hand2").grid(
            row=btn_row, column=1, pady=12, padx=8, sticky=tk.W)

    def _new_from_preset(self, preset_name: str):
        preset = HARDWARE_PRESETS.get(preset_name, HARDWARE_PRESETS["ESP32-DevKit"])
        self._filepath = None
        self._name_var.set("Custom")
        self._base_var.set("1")
        self._flag_var.set("0")
        self._build_preset_grid(preset)
        n = len(preset.visible_slots)
        self._status(f"New — {preset.name}  ({n} visible slots)")

    # -----------------------------------------------------------------------
    # File operations
    # -----------------------------------------------------------------------

    def _cmd_open(self):
        if self._modified and not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            title="Open template",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(SCRIPT_DIR / "examples"),
        )
        if path:
            self._open_file(Path(path))

    def _open_file(self, path: Path):
        try:
            data  = json.loads(path.read_text(encoding="utf-8"))
            clean = {k: v for k, v in data.items() if not k.startswith("_")}
            if "GPIO" in clean and "NAME" in clean:
                self._load_tasmota_dict(clean)
            else:
                self._load_human_dict(clean)
            self._filepath = path
            self._modified = False
            self._status(f"Opened: {path.name}")
            self._update_title()
        except Exception as exc:
            messagebox.showerror("Open error", str(exc))

    def _cmd_save(self):
        if self._filepath is None:
            self._cmd_save_as()
        else:
            self._write_file(self._filepath)

    def _cmd_save_as(self):
        path = filedialog.asksaveasfilename(
            title="Save human JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(self._filepath.parent if self._filepath
                          else SCRIPT_DIR / "examples"),
        )
        if path:
            self._filepath = Path(path)
            self._write_file(self._filepath)

    def _write_file(self, path: Path):
        try:
            d = self._template_to_dict()
            path.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
            self._modified = False
            self._status(f"Saved: {path.name}")
            self._update_title()
        except Exception as exc:
            messagebox.showerror("Save error", str(exc))

    def _cmd_view(self):
        import tempfile, os as _os
        try:
            d = self._template_to_dict()
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                             delete=False, encoding="utf-8") as f:
                json.dump(d, f, indent=2)
                tmp = f.name
            tasmota_json = _run_convert("encode", tmp)
            _os.unlink(tmp)
            self.clipboard_clear()
            self.clipboard_append(tasmota_json)
            self._show_view_popup(tasmota_json)
            self._status("Tasmota JSON copied to clipboard")
        except Exception as exc:
            messagebox.showerror("Encode error", str(exc))

    def _show_view_popup(self, json_str: str):
        win = tk.Toplevel(self)
        win.title("Tasmota JSON — Configuration > Other > Template")
        win.configure(bg=C_BG)
        win.geometry("740x170")

        tk.Label(win, text="Paste this JSON in  Configuration > Other > Template:",
                 bg=C_BG, fg=C_FG, anchor=tk.W,
                 font=("Helvetica", 9), padx=10, pady=6).pack(fill=tk.X)

        txt = tk.Text(win, height=4, bg="#1a1a1a", fg="#00e5ff", wrap=tk.WORD,
                      font=("Courier", 9), relief=tk.FLAT, padx=8, pady=6)
        txt.insert("1.0", json_str)
        txt.configure(state=tk.DISABLED)
        txt.pack(fill=tk.BOTH, expand=True, padx=10)

        bf = tk.Frame(win, bg=C_BG)
        bf.pack(pady=6)
        tk.Button(bf, text="Close", command=win.destroy,
                  bg=C_BORDER, fg=C_BTN_FG, relief=tk.FLAT,
                  font=("Helvetica", 9), padx=10, cursor="hand2").pack(
            side=tk.LEFT, padx=4)
        tk.Button(bf, text="Copy again",
                  command=lambda: (self.clipboard_clear(),
                                   self.clipboard_append(json_str)),
                  bg=C_ACCENT, fg=C_BTN_FG, relief=tk.FLAT,
                  font=("Helvetica", 9), padx=10, cursor="hand2").pack(
            side=tk.LEFT, padx=4)

    def _cmd_check(self):
        """Validate configuration consistency."""
        errors:   list[str] = []
        warnings: list[str] = []
        encoded = self._get_encoded_list()

        # Build (gid, pin, slot_pos) usage list, skip true NONE (val==0)
        usage: list[tuple[int, int, int]] = []
        for slot_pos, val in enumerate(encoded):
            if val == 0:
                continue
            gid, pin = decode_pin(val)
            usage.append((gid, pin, slot_pos))

        gm  = self._gpio_map
        rev = self._rev_map

        def gid_of(name: str) -> int | None:
            return gm.get(name)

        # Rule 1 — no duplicate (gid, pin) pairs
        seen: dict[tuple[int, int], int] = {}
        for gid, pin, slot_pos in usage:
            key = (gid, pin)
            if key in seen:
                name = rev.get(gid, f"GPIO_{gid}")
                errors.append(
                    f"Duplicate {name}:{pin}  "
                    f"(slots {seen[key]} and {slot_pos})"
                )
            else:
                seen[key] = slot_pos

        # Rule 2 — functional groups share an index space: Button, Switch,
        #           Relay, Led.  All variants within a group map to the same
        #           logical index, so e.g. Button:0 and Button_n:0 conflict.
        #
        #   Source: support_tasmota.ino + xdrv_67_mcp23xxx.ino
        #     mpin -= (AGPIO(GPIO_KEY1_NP) - AGPIO(GPIO_KEY1))  → same slot
        #
        FUNCTIONAL_GROUPS: list[tuple[str, list[str]]] = [
            ("Button", [
                "GPIO_KEY1", "GPIO_KEY1_NP", "GPIO_KEY1_INV", "GPIO_KEY1_INV_NP",
                "GPIO_KEY1_PD", "GPIO_KEY1_INV_PD", "GPIO_KEY1_TC",
            ]),
            ("Switch", [
                "GPIO_SWT1", "GPIO_SWT1_NP", "GPIO_SWT1_PD",
            ]),
            ("Relay", [
                "GPIO_REL1", "GPIO_REL1_INV", "GPIO_REL1_BI", "GPIO_REL1_BI_INV",
            ]),
            ("Led", [
                "GPIO_LED1", "GPIO_LED1_INV", "GPIO_LED1_INV_OPENDRAIN",
            ]),
        ]

        for group_name, gpio_names in FUNCTIONAL_GROUPS:
            # Collect {logical_index: [(gpio_name, slot_pos), ...]}
            index_users: dict[int, list[tuple[str, int]]] = {}
            for gpio_name in gpio_names:
                gid = gid_of(gpio_name)
                if gid is None:
                    continue
                for u_gid, pin, slot_pos in usage:
                    if u_gid == gid:
                        index_users.setdefault(pin, []).append((gpio_name, slot_pos))
            for idx, users in index_users.items():
                if len(users) > 1:
                    parts = ", ".join(
                        f"{n.removeprefix('GPIO_')} (slot {s})" for n, s in users
                    )
                    errors.append(
                        f"{group_name} index {idx} used by multiple variants: {parts}"
                    )

        # Rule 3 — I2C: each bus index must have both SDA and SCL
        scl_ids = {gm[g] for g in ("GPIO_I2C_SCL",) if g in gm}
        sda_ids = {gm[g] for g in ("GPIO_I2C_SDA",) if g in gm}
        scl_pins = {pin for gid, pin, _ in usage if gid in scl_ids}
        sda_pins = {pin for gid, pin, _ in usage if gid in sda_ids}
        for i in sorted(scl_pins - sda_pins):
            errors.append(f"I2C bus {i}: SCL present but SDA missing")
        for i in sorted(sda_pins - scl_pins):
            errors.append(f"I2C bus {i}: SDA present but SCL missing")

        # Rule 4 — SPI: each bus index must have CLK, MISO, MOSI
        spi_groups: dict[str, set[int]] = {}
        for gpio_name in ("GPIO_SPI_CLK", "GPIO_SPI_MISO", "GPIO_SPI_MOSI"):
            gid = gid_of(gpio_name)
            if gid is None:
                continue
            spi_groups[gpio_name] = {pin for g, pin, _ in usage if g == gid}
        if any(spi_groups.values()):
            all_spi = (spi_groups.get("GPIO_SPI_CLK",  set()) |
                       spi_groups.get("GPIO_SPI_MISO", set()) |
                       spi_groups.get("GPIO_SPI_MOSI", set()))
            for idx in sorted(all_spi):
                missing = []
                if idx not in spi_groups.get("GPIO_SPI_CLK",  set()): missing.append("CLK")
                if idx not in spi_groups.get("GPIO_SPI_MISO", set()): missing.append("MISO")
                if idx not in spi_groups.get("GPIO_SPI_MOSI", set()): missing.append("MOSI")
                if missing:
                    errors.append(f"SPI bus {idx}: missing {', '.join(missing)}")

        # Rule 5 — TM1638: CLK, DIO, STB must all be present (same count)
        tm_groups: dict[str, int] = {}
        for gpio_name in ("GPIO_TM1638CLK", "GPIO_TM1638DIO", "GPIO_TM1638STB"):
            gid = gid_of(gpio_name)
            tm_groups[gpio_name] = sum(1 for g, _, _ in usage if g == gid) if gid else 0
        tm_counts = set(tm_groups.values())
        if tm_counts - {0}:
            if len(tm_counts) > 1 or 0 in tm_counts:
                missing = [n.removeprefix("GPIO_TM1638") for n, c in tm_groups.items() if c == 0]
                errors.append(f"TM1638: missing {', '.join(missing)} — need CLK+DIO+STB")

        # Show results
        if not errors and not warnings:
            messagebox.showinfo("Check — OK",
                                "No consistency errors found.",
                                parent=self)
        else:
            lines = []
            for e in errors:
                lines.append(f"ERROR:   {e}")
            for w in warnings:
                lines.append(f"WARNING: {w}")
            messagebox.showerror(
                "Check — Issues found",
                "\n".join(lines),
                parent=self,
            )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _mark_modified(self):
        if not self._modified:
            self._modified = True
            self._update_title()

    def _confirm_discard(self) -> bool:
        return messagebox.askyesno("Unsaved changes", "Discard unsaved changes?")

    def _status(self, msg: str):
        self._status_var.set(msg)

    def _update_title(self):
        name = self._name_var.get() or "Untitled"
        mod  = " *" if self._modified else ""
        fp   = f" — {self._filepath.name}" if self._filepath else ""
        self.title(f"Tasmota GPIO Template{fp} [{name}]{mod}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tasmota GPIO template graphical editor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="store_true",
                        help="Print version and exit")
    parser.add_argument("--input", type=Path, metavar="FILE",
                        help="Open template file on startup")
    parser.add_argument("--based-on", metavar="NAME",
                        help="Start from hardware preset (ESP32, ESP32-S3, …)")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.version:
        print(f"gpio-template-ui {TOOL_VERSION}  (Tasmota {TASMOTA_VERSION})")
        sys.exit(0)

    # Re-launch in background to free the terminal
    _relaunch_background()

    app = TemplateEditor(
        initial_file=args.input,
        based_on=getattr(args, "based_on", None),
    )
    app.mainloop()


if __name__ == "__main__":
    main()
