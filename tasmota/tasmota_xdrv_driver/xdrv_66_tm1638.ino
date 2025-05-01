/*
  xdrv_66_tm1638.ino - TM1638 8 switch, led and 7 segment unit support for Tasmota

  Copyright (C) 2021  Theo Arends

  This program is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/

#ifdef USE_TM1638
/*********************************************************************************************\
 * TM1638 8 switch, led and 7 segment
 *
 * Uses GPIO TM1638 DIO, TM1638 CLK and TM1638 STB
 * 
 * Leds 0..7 are connected to SEG9 (Grid1=led0, grid2=led1, etc) => TM1638_MAX_LEDS in range [1..8]
 * Leds 8..15 are  connected to SEG10 => TM1638_MAX_LEDS in range [9..16]
\*********************************************************************************************/

#define XDRV_66               66

// BUTTON & SWITCH are mutual exclusive
#ifdef TM1638_USE_AS_BUTTON
#define TM1638_USE_BUTTONS         // Use keys as buttons
#endif
#ifdef TM1638_USE_AS_SWITCH
#undef TM1638_USE_BUTTONS          // Use keys as switches
#endif

// Define other parameters if not assigned
#ifndef TM1638_MAX_DISPLAYS
#define TM1638_MAX_DISPLAYS   8
#endif
#ifndef TM1638_MAX_KEYS
#define TM1638_MAX_KEYS       8
#endif
#ifndef TM1638_MAX_LEDS
#define TM1638_MAX_LEDS       8
#endif
#ifndef TM1638_BRIGHTNESS
#define TM1638_BRIGHTNESS     0    // Brightness from 0 to 7
#endif
#ifndef TM1638_DISPLAY_ON
#define TM1638_DISPLAY_ON     1    // Display off (0) or on (1)
#endif

#define TM1638_COLOR_NONE     0
#define TM1638_COLOR_RED      1
#define TM1638_COLOR_GREEN    2

#define TM1638_CLOCK_DELAY    1    // uSec

#if TM1638_MAX_LEDS > 16
#error "TM1638 driver accepts up to 16 leds connected to SEG9 & SEG10"
#endif

#if TM1638_MAX_KEYS > 8
#error "TM1638 driver accepts up to 8 keys"
#endif

struct TM1638 {
  int8_t clock_pin = 0;
  int8_t data_pin = 0;
  int8_t strobe_pin = 0;
  int8_t key_offset;  
  bool detected = false;
  
  uint8_t max_pins;
  uint8_t relay_max;
  uint8_t relay_offset;
  uint32_t relay_inverted;
  bool base;
  uint8_t led_offset;
  uint8_t led_inverted;
  uint8_t led_max;
} Tm1638;

uint16_t *Tm1638_gpio_pin = nullptr;

/*********************************************************************************************\
 * Pieces from library https://github.com/rjbatista/tm1638-library
 *    and from library https://github.com/MartyMacGyver/TM1638-demos-and-examples
\*********************************************************************************************/

void Tm16XXSend(uint8_t data) {
	for (uint32_t i = 0; i < 8; i++) {          // 8 bits
    digitalWrite(Tm1638.data_pin, !!(data & (1 << i)));
    digitalWrite(Tm1638.clock_pin, LOW);
    delayMicroseconds(TM1638_CLOCK_DELAY);
    digitalWrite(Tm1638.clock_pin, HIGH);
  }
}

void Tm16XXSendCommand(uint8_t cmd) {
  digitalWrite(Tm1638.strobe_pin, LOW);
  Tm16XXSend(cmd);
  digitalWrite(Tm1638.strobe_pin, HIGH);
}

void TM16XXSendData(uint8_t address, uint8_t data) {
  // TM_WRITE_LOC 0x44 - Write to a location
  // TM_SEG_ADR   0xC0 - leftmost segment Address C0 C2 C4 C6 C8 CA CC CE
  // TM_LEDS_ADR  0xC1 - Leftmost LED address C1 C3 C5 C7 C9 CB CD CF
  Tm16XXSendCommand(0x44);
  digitalWrite(Tm1638.strobe_pin, LOW);
  Tm16XXSend(0xC0 | address);
  Tm16XXSend(data);
  digitalWrite(Tm1638.strobe_pin, HIGH);
}

uint8_t Tm16XXReceive(void) {
  uint8_t temp = 0;

  // Pull-up on
  pinMode(Tm1638.data_pin, INPUT);
  digitalWrite(Tm1638.data_pin, HIGH);

  for (uint32_t i = 0; i < 8; ++i) {          // 8 bits
    digitalWrite(Tm1638.clock_pin, LOW);
    delayMicroseconds(TM1638_CLOCK_DELAY);
    temp |= digitalRead(Tm1638.data_pin) << i;
    digitalWrite(Tm1638.clock_pin, HIGH);
  }

  // Pull-up off
  pinMode(Tm1638.data_pin, OUTPUT);
  digitalWrite(Tm1638.data_pin, LOW);

  return temp;
}

/*********************************************************************************************/
/* Tasmota gpio compatibility */

int Tm1638Pin(uint32_t gpio, uint32_t index = 0);
int Tm1638Pin(uint32_t gpio, uint32_t index) {
  uint16_t real_gpio = gpio << 5;
  uint16_t mask = 0xFFE0;
  if (index < GPIO_ANY) {
    real_gpio += index;
    mask = 0xFFFF;
  }
  for (uint32_t i = 0; i <= Tm1638.max_pins; i++) {
    if ((Tm1638_gpio_pin[i] & mask) == real_gpio) {
      return i;                                        // Pin number configured for gpio
    }
  }
  return -1;                                           // No pin used for gpio
}

bool Tm1638PinUsed(uint32_t gpio, uint32_t index = 0);
bool Tm1638PinUsed(uint32_t gpio, uint32_t index) {
  return (Tm1638Pin(gpio, index) >= 0);
}

uint32_t Tm1638GetPin(uint32_t lpin) {
  if (lpin <= Tm1638.max_pins) {
    return Tm1638_gpio_pin[lpin];
  } else {
    return GPIO_NONE;
  }
}
/*********************************************************************************************/

void Tm1638SetLED(uint8_t color, uint8_t pos) {
  TM16XXSendData((pos << 1) + 1, color);
}

uint8_t Tm1638GetButtons(void) {
  // TM_BUTTONS_MODE 0x42 - Buttons mode
  digitalWrite(Tm1638.strobe_pin, LOW);
  Tm16XXSend(0x42);
  uint8_t keys = 0;
  for (uint32_t i = 0; i < 4; i++) {
    keys |= Tm16XXReceive() << i;
  }
  digitalWrite(Tm1638.strobe_pin, HIGH);

  return keys;
}

/*********************************************************************************************/

bool Tm1638AddItem(uint8_t &item) {
  if (item >= 32) {
    AddLog(LOG_LEVEL_INFO, PSTR("TM1638: Max ITEM reached"));
    return false;
  }
  item++;
  return true;
}
bool Tm1638LoadTemplate(void) {
  String TmImplt = "";
  #ifdef USE_UFILESYS
    TmImplt = TfsLoadString("/tm1638out.dat");
    AddLog(LOG_LEVEL_INFO, PSTR("TM1638: Loading file /tm1638out.dat => %s"), TmImplt.c_str());
  #endif  // USE_UFILESYS
  #ifdef USE_RULES
    if (!TmImplt.length()) {
      TmImplt = RuleLoadFile("TM1638OUT.DAT");
      AddLog(LOG_LEVEL_INFO, PSTR("TM1638: Loading RULES TM1638OUT.dat => %s"), TmImplt.c_str());
    }
  #endif  // USE_RULES
  #ifdef USE_SCRIPT
    if (!TmImplt.length()) {
      TmImplt = ScriptLoadSection(">y");
      AddLog(LOG_LEVEL_INFO, PSTR("TM1638: Loading SCRIPT => %s"), TmImplt.c_str());
    }
  #endif  // USE_SCRIPT
  uint32_t len = TmImplt.length() +1;
  if (len < 7) { return false; }     // No TmImplt found

  JsonParser parser((char*)TmImplt.c_str());
  JsonParserObject root = parser.getRootObject();
  if (!root) { return false; }

  // rule3 on file#Tm1638.dat do {"NAME":"TM1638-16","BASE:1","GPIO":[0,0,0,0,0,0,0,0,0,224,225,226,227,228,229,230,231]} endon
  // rule3 on file#Tm1638.dat do {"NAME":"TM1638-8","BASE:0","GPIO":[263,262,261,260,259,258,257,256]} endon    
  JsonParserToken val = root[PSTR(D_JSON_BASE)];
  if (val) {
    Tm1638.base = (val.getUInt()) ? true : false;
  }
  val = root[PSTR(D_JSON_NAME)];
  if (val) {
    AddLog(LOG_LEVEL_DEBUG, PSTR("TM1638: Base %d, Template '%s'"), Tm1638.base, val.getStr());
  }
  JsonParserArray arr = root[PSTR(D_JSON_GPIO)];
  if (arr) {
    uint32_t pin = 0;
    for (pin; pin < TM1638_MAX_LEDS; pin++) {        
      JsonParserToken val = arr[pin];
      if (!val) { break; }
      uint16_t mpin = val.getUInt();
      if (mpin) {                                      // Above GPIO_NONE
        if ((mpin >= AGPIO(GPIO_REL1)) && (mpin < (AGPIO(GPIO_REL1) + MAX_RELAYS_SET)) && Tm1638AddItem(Tm1638.relay_max)) {
          
        }
        else if ((mpin >= AGPIO(GPIO_REL1_INV)) && (mpin < (AGPIO(GPIO_REL1_INV) + MAX_RELAYS_SET)) && Tm1638AddItem(Tm1638.relay_max)) {
          bitSet(Tm1638.relay_inverted, mpin - AGPIO(GPIO_REL1_INV));
          mpin -= (AGPIO(GPIO_REL1_INV) - AGPIO(GPIO_REL1));
          
        }
        else if ((mpin >= AGPIO(GPIO_LED1)) && (mpin < (AGPIO(GPIO_LED1) + MAX_LEDS)) && Tm1638AddItem(Tm1638.led_max)) {                              
          
        }
        else if ((mpin >= AGPIO(GPIO_LED1_INV)) && (mpin < (AGPIO(GPIO_LED1_INV) + MAX_LEDS)) && Tm1638AddItem(Tm1638.led_max)) {
          bitSet(Tm1638.led_inverted, mpin - AGPIO(GPIO_LED1_INV));
          mpin -= (AGPIO(GPIO_LED1_INV) - AGPIO(GPIO_LED1));          
          
        }
        else if (mpin == AGPIO(GPIO_LEDLNK) && !TasmotaGlobal.ledlnk_present) {                           
          TasmotaGlobal.ledlnk_present++;
          
        }
        else if (mpin == AGPIO(GPIO_LEDLNK_INV)&& !TasmotaGlobal.ledlnk_present) {          
          mpin -= (AGPIO(GPIO_LEDLNK_INV) - AGPIO(GPIO_LEDLNK));                  
          TasmotaGlobal.ledlnk_present++;
          TasmotaGlobal.ledlnk_inverted=1;
        }
        else if (mpin == AGPIO(GPIO_OUTPUT_HI)) {
          Tm1638SetLED(TM1638_COLOR_RED , pin);          
        }
        else if (mpin == AGPIO(GPIO_OUTPUT_LO)) {          
          Tm1638SetLED(TM1638_COLOR_NONE, pin);
        }
        else { mpin = 0; }
        Tm1638_gpio_pin[pin] = mpin;
      }
    }
    Tm1638.max_pins = pin;                             // Max number of configured pins
    AddLog(LOG_LEVEL_INFO, PSTR("TM1638: Pins %d (Relays=%d/Leds=%d/LNK=%d), Base=%d, Offset(R=%d/L=%d)"), Tm1638.max_pins, Tm1638.relay_max, Tm1638.led_max, TasmotaGlobal.ledlnk_present,Tm1638.relay_offset, Tm1638.led_offset);
  } else {
    AddLog(LOG_LEVEL_ERROR, PSTR("TM1638: No GPIO defined"));
  }
//  AddLog(LOG_LEVEL_DEBUG, PSTR("TM1638: Pins %d, Tm1638_gpio_pin %*_V"), Tm1638.max_pins, Tm1638.max_pins, (uint8_t*)Tm1638_gpio_pin);

  return true;
}


/*********************************************************************************************/

void TmInit(void) {
  if (PinUsed(GPIO_TM1638CLK) && PinUsed(GPIO_TM1638DIO) && PinUsed(GPIO_TM1638STB)) {
    Tm1638.clock_pin = Pin(GPIO_TM1638CLK);
    Tm1638.data_pin = Pin(GPIO_TM1638DIO);
    Tm1638.strobe_pin = Pin(GPIO_TM1638STB);

    pinMode(Tm1638.data_pin, OUTPUT);
    pinMode(Tm1638.clock_pin, OUTPUT);
    pinMode(Tm1638.strobe_pin, OUTPUT);

    digitalWrite(Tm1638.strobe_pin, HIGH);
    digitalWrite(Tm1638.clock_pin, HIGH);

    // TM_WRITE_INC  0x40 - Incremental write
    Tm16XXSendCommand(0x40);
    // TM_BRIGHT_ADR 0x88 - Brightness address
    Tm16XXSendCommand(0x80 | TM1638_DISPLAY_ON << 3 | TM1638_BRIGHTNESS);

    // TM_SEG_ADR   0xC0  - leftmost segment Address C0 C2 C4 C6 C8 CA CC CE
    // TM_LEDS_ADR  0xC1  - Leftmost LED address C1 C3 C5 C7 C9 CB CD CF
    digitalWrite(Tm1638.strobe_pin, LOW);
    Tm16XXSend(0xC0);                         // TM_SEG_ADR left most
    for (uint32_t i = 0; i < TM1638_MAX_DISPLAYS * 2; i++) {
      Tm16XXSend(0x00);                       // Init displays and leds
    }
    digitalWrite(Tm1638.strobe_pin, HIGH);


    Tm1638_gpio_pin = (uint16_t*)calloc(TM1638_MAX_LEDS, 2);
    if (!Tm1638_gpio_pin) { return; }

    if (!Tm1638LoadTemplate()) {
      AddLog(LOG_LEVEL_INFO, PSTR("TM1638: No valid template found"));  // Too many GPIO's
      
      return;
    }

    Tm1638.relay_offset = TasmotaGlobal.devices_present;
    Tm1638.relay_max -= UpdateDevicesPresent(Tm1638.relay_max);

    Tm1638.led_offset = TasmotaGlobal.leds_present; // led_offset is used in case of BASE=0 (relative)
    TasmotaGlobal.leds_present += Tm1638.led_max;
    
    // Set offset to -1 in init phase
    // offset will be properly assigned during Add_Button/add_switch command
    Tm1638.key_offset = -1;
    Tm1638.detected = true;
  }
}

void TmLoop(void) {
  uint8_t keys = Tm1638GetButtons();
  for (uint32_t i = 0; i < TM1638_MAX_KEYS; i++) {
    uint32_t state = keys &1;
#ifdef TM1638_USE_BUTTONS
    ButtonSetVirtualPinState(Tm1638.key_offset +i, state);
#else
    SwitchSetVirtualPinState(Tm1638.key_offset +i, state);
#endif
    keys >>= 1;
  }
}

void TmPower(void) {
  // XdrvMailbox.index = 32-bit rpower bit mask
  // Use absolute relay indexes unique with main template
  power_t rpower = XdrvMailbox.index;
  uint32_t relay_max = TasmotaGlobal.devices_present;
  if (!Tm1638.base) {
    // Use relative and sequential relay indexes
    rpower >>= Tm1638.relay_offset;
    relay_max = Tm1638.relay_max;
  }
  DevicesPresentNonDisplayOrLight(relay_max);          // Skip display and/or light(s)
  if (relay_max>TM1638_MAX_LEDS){
    relay_max=TM1638_MAX_LEDS;
    // add log
  }

  for (uint32_t index = 0; index < relay_max; index++) {
    power_t state = rpower &1;
    if (Tm1638PinUsed(GPIO_REL1, index)) {
      state = bitRead(Tm1638.relay_inverted, index) ? !state : state;
      if (index<8) {
        uint8_t color = (state) ? TM1638_COLOR_RED : TM1638_COLOR_NONE;
        Tm1638SetLED(color, index);
      } else {
        uint8_t color = (state) ? TM1638_COLOR_GREEN : TM1638_COLOR_NONE;
        Tm1638SetLED(color, index);
      }    
    }
    rpower >>= 1;                                      // Select next power
  }
}

void TmLedPower() {
  uint32_t index = XdrvMailbox.index;    
  if (!Tm1638.base) {
    // Use relative and sequential led indexes
    index -= Tm1638.led_offset;    
  }
  power_t state = bitRead(Tm1638.led_inverted, index) ? !XdrvMailbox.payload : XdrvMailbox.payload;
  uint8_t color = (state)?TM1638_COLOR_RED : TM1638_COLOR_NONE;

  if (Tm1638PinUsed(GPIO_LED1, index)) {
    uint32_t pin = Tm1638Pin(GPIO_LED1, index) & 0x3F;   // Fix possible overflow over 63 gpios
    Tm1638SetLED(color, index);      
    AddLog(LOG_LEVEL_DEBUG, PSTR("TM1638: TmLedPower %d, Index=%d, Color=%d, pin=0x%x"), XdrvMailbox.index, index, color, pin);
  }else
    AddLog(LOG_LEVEL_DEBUG_MORE, PSTR("TM1638: TmLedPower %d, Index=%d, Pin=(not assigned)"), XdrvMailbox.index, index);  
}

void Tm1638LedLink() {
  bool state = (XdrvMailbox.index)?true:false;
  if (TasmotaGlobal.ledlnk_inverted) state = !state;  
  if (Tm1638PinUsed(GPIO_LEDLNK, 0)) {    
    uint32_t pin = Tm1638Pin(GPIO_LEDLNK, 0) & 0x3F;   // Fix possible overflow over 63 gpios  
    Tm1638SetLED((state)?TM1638_COLOR_RED : TM1638_COLOR_NONE, pin);          
    AddLog(LOG_LEVEL_DEBUG, PSTR("TM1638: LedLink, Pin=%d, state=%d, inverted=%d"), pin, state, TasmotaGlobal.ledlnk_inverted);
  } 
}

bool TmAddKey(void) {
  // XdrvMailbox.index = button/switch index
  if (Tm1638.key_offset < 0) { Tm1638.key_offset = XdrvMailbox.index; }
  uint32_t index = XdrvMailbox.index - Tm1638.key_offset;
  if (index >= TM1638_MAX_KEYS) { return false; }
/*
  uint8_t keys = Tm1638GetButtons();
  uint32_t state = bitRead(keys, index);
  AddLog(LOG_LEVEL_DEBUG, PSTR("DBG: Default state %d"), state);
  XdrvMailbox.index = state;                  // Default is 0 - Button will also set invert
*/
  XdrvMailbox.index = 0;                      // Default is 0 - Button will also set invert
  return true;
}



/*********************************************************************************************\
 * Interface
\*********************************************************************************************/

bool Xdrv66(uint32_t function) {
  bool result = false;

  if (FUNC_SETUP_RING2 == function) {
    TmInit();
  } else if (Tm1638.detected) {
    switch (function) {
      case FUNC_EVERY_50_MSECOND:
        TmLoop();
        break;
      case FUNC_SET_POWER:
        TmPower();
        break;
#ifdef TM1638_USE_BUTTONS
      case FUNC_ADD_BUTTON:
#else
      case FUNC_ADD_SWITCH:
#endif
        result = TmAddKey();
        break;
      case FUNC_ACTIVE:
        result = true;
        break;
      case FUNC_LED:
        TmLedPower();
      break;
      case FUNC_LED_LINK:
        Tm1638LedLink();
      break;   

    }
  }
  return result;
}

#endif  // USE_TM1638