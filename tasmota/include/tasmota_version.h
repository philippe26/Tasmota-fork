/*
  tasmota_version.h - Version header file for Tasmota

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

#ifndef _TASMOTA_VERSION_H_
#define _TASMOTA_VERSION_H_

#define TASMOTA_SHA_SHORT                      // Filled by Github sed

// Modif PG 16/08/2025 - Add 0x80 to minor version to indicate a modified release vs arends delivery

/* custom Builds
   0x03: official arends delivery
   0x80: Add led support (including mpc23xx and TM1638 drivers)
   0x82: Add topology support for MCP23xx (enforce i2c address recognition)
   0x83: Add information of assigned power of display
   0x84: Bugfix I2C speed (restore proper value) & add i2cSpeed command
   0x85: Prevent flooding of readsensors logs when sensors DS18B20 is disconnected
   0x86: Add tasmota.get_button_state(idx) Berry binding to read debounced button state
   0x87: Add support for led opendrain configuration for gpio (GPIO_LED1_INV_OPENDRAIN: 11744+)
*/
#define TASMOTA_BUILD      0x87

const uint32_t TASMOTA_VERSION = 0x0E040100 + TASMOTA_BUILD;   // 14.4.1.build

#endif  // _TASMOTA_VERSION_H_
