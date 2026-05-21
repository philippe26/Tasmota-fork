# Analyse merge : `development` → `scada_projects`

**Base commune :** `ba3c00ec` (Change GPIOViewer v1.6.0→v1.6.1)  
**scada_projects HEAD :** `a1e8690f` (20 commits depuis la base)  
**development HEAD :** `a90c539899` (20 875 commits depuis la base — v14.4.1 → v15.0.1+)  
**Date analyse :** 2026-05-19  
**Note :** `development` locale resynchronisée sur `official/development` via `git reset --hard`
avant cette analyse (elle était figée 6 mois en retard).

---

## 1. Vue d'ensemble

| Dimension | Valeur |
|---|---|
| Commits development à intégrer | 20 875 |
| Commits scada_projects | 20 |
| Fichiers modifiés dans development | 3 317 |
| Fichiers modifiés dans scada_projects | 23 |
| **Fichiers en conflit potentiel** | **16** |
| Fichiers scada-exclusifs (pas de risque) | 7 |

---

## 2. Synthèse des évolutions de `development` (v14.4.1 → v15.0.1+)

### Noyau C++ / infrastructure
- **`MAX_LEDS`** : 4 → 32 ; `led_power`/`led_inverted` `uint8_t` → `power_t`
- **`FUNC_LED`** : nouveau hook XDrv pour déléguer les LEDs à un driver externe
- **`ledlnk_present`** ajouté dans `TasmotaGlobal`
- **`CmndLedPower`** réécrit autour de `ledlnk_present` (remplace `PinUsed(GPIO_LEDLNK)`)
- **`GPIO_LED1_INV_OPENDRAIN`** ajouté dans `tasmota_template.h` (même fonctionnalité que scada)
- **`MAX_I2C` / `MAX_RMT`** refactorisés via macros SOC (`SOC_I2S_NUM`, `SOC_RMT_GROUPS`…)
- **`support_a_i2c.ino`** : refactoring complet I2C — `MAX_I2C`, second bus ESP8266, `I2cSetClock()` réécrit, suppression slave support
- **`xdrv_67_mcp23xxx.ino`** : ajout paramètre `.bus` à tous les appels I2C, scan multi-bus, ODR interrupt, open-drain interrupt fixes
- **`CmndJsonPP`** : nouvelle commande `JsonPP` pretty-print JSON
- **`SleepSkip()`**, **`USE_XYZMODEM`**, **`USE_TELNET`**, **`USE_WIREGUARD`**, **`USE_WEB_STATUS_LINE`**
- **Auto-switch safeboot** si 10 reboots rapides (ESP32)
- **platformio.ini** : ESP8266 platform 2024→2025, `lib_ignore` audio, réorganisation
- **`FUNC_WEB_STATUS_LEFT/RIGHT`** : nouveaux hooks webUI

### Berry
- **`tasmota.add_rule_once()`**, **`tasmota.defer()`**, **`tasmota.when_network_up()`**
- **`tasmota.arch()`** → `static_func`
- **`WSContentSendRaw_P`** remplace `WSContentSend_P` dans berry webserver
- **`SerialBridgeWrite`** remplace `SerialBridgePrintf`
- **`be_tasmota_lib.c`** : nouvelles closures dans table de dispatch

### Périphériques / drivers
- **Hosted MCU** (nouveau driver ESP32 + OTA)
- **LoRaWAN** : framework décodeurs + Milesight/Glamos
- **PN532 NFC**, **C8-CO2-5K**, **V9240**, **LD2402**, **HSDIO** GPIO
- **HASPmota** buttonmatrix, **Berry animation** framework
- **`xdrv_13_display.ino`** : `ApplyDisplayDimmer(uint8_t)`, `jpeg_decoder.h`, `Power` dans réponse JSON

---

## 3. Analyse des conflits par fichier

### 🔴 Risque ÉLEVÉ — réécriture dans le même secteur

#### `tasmota/tasmota_support/support_a_i2c.ino`
**scada :** +20 lignes — ajout `default_frequency[]`, modification signature `I2cSetClock(freq, bus, force_default)`, restauration depuis `default_frequency` au lieu de hardcoder 100kHz, log de la fréquence active  
**development :** +132 lignes — refactoring profond : `USE_I2C_BUS2_ESP8266` supprimé, `frequency[2]` → `frequency[MAX_I2C]`, `active[2][4]` → `active[MAX_I2C][4]`, `I2cSetClock()` réécrit, slave support supprimé, scan multi-bus  
**Conflit :** les deux branches modifient `I2cSetClock()` et la structure `I2C`. La version dev est une réécriture profonde ; scada y a ajouté `default_frequency` et `force_default`. **Résolution manuelle — réintégrer la logique `default_frequency` dans la version dev.**

#### `tasmota/tasmota_support/support_command.ino`
**scada :** +66 lignes — ajout `CmndI2cSpeed`, refactoring `CmndLedPower` (mode `ledlnk_present`, réponse JSON enrichie)  
**development :** +266 lignes — `CmndLedPower` réécrit différemment, `CmndJsonPP`, réorganisation table de dispatch  
**Conflit :** `CmndLedPower` réécrite dans les deux branches de façon incompatible. **Résolution manuelle obligatoire — s'assurer que le dispatch `FUNC_LED` (scada) est présent dans la version dev.**

#### `tasmota/tasmota_support/support_tasmota.ino`
**scada :** +78 lignes — hook `FUNC_LED` dans `SetLedPowerIdx()`, refactoring `SetLedLink()`/`UpdateLedPower()`, suppression mode legacy LedLnk  
**development :** +36 lignes — `FUNC_WEB_STATUS_LEFT/RIGHT`, `SleepSkip()`, `USE_XYZMODEM`, `SetMinimumSeriallog()`  
**Conflit :** zones `SetLedPowerIdx` et `UpdateLedPower` modifiées des deux côtés. **Résolution manuelle — réintégrer le hook `FUNC_LED` scada dans la version dev.**

#### `tasmota/tasmota_xdrv_driver/xdrv_67_mcp23xxx.ino`
**scada :** +195 lignes — support LEDs/LedLnk, topology, opendrain, `get_button_state`, `AlarmMode`-related callbacks  
**development :** ~200 lignes — ajout paramètre `.bus` à tous les appels I2C (`I2cRead8`, `I2cWrite8`…), scan multi-bus, ODR interrupt, open-drain interrupt fixes  
**Conflit :** modifications parallèles sur le même driver. La version dev refactorise les appels I2C en profondeur ; scada ajoute des fonctionnalités LEDs/topology. **Résolution manuelle la plus complexe** — les deux ensembles de modifications sont fonctionnellement orthogonaux mais touchent les mêmes fonctions.

#### `tasmota/include/tasmota.h`
**scada :** `led_power`/`led_inverted` `uint8_t`→`power_t`, `FUNC_LED`, `MAX_LEDS` 4→32, `ledlnk_present`  
**development :** mêmes changements + refactoring `MAX_I2S`/`MAX_RMT` avec macros SOC, `FUNC_WEB_STATUS_LEFT/RIGHT`  
**Conflit :** les deux branches font les mêmes changements structurels sur les LEDs. La version dev est le superset. **Fusion probable sans perte**, mais vérification ligne à ligne requise pour éviter les doublons.

#### `tasmota/include/tasmota_template.h`
**scada :** `GPIO_LED1_INV_OPENDRAIN` + chaîne + `AGPIO` dans table  
**development :** même `GPIO_LED1_INV_OPENDRAIN` + +150 lignes (C8-CO2, V9240, LD2402, HSDIO, SDIO refactorisé)  
**Conflit :** ⚠️ **risque de décalage d'enum silencieux** — development insère des GPIO supplémentaires avant `GPIO_SENSOR_END`, la valeur numérique de `GPIO_LED1_INV_OPENDRAIN` peut différer. **Après merge, vérifier les valeurs numériques des deux côtés avant de flasher.**

#### `lib/libesp32/berry_tasmota/src/be_tasmota_lib.c`
**scada :** ajout `l_getbuttonstate` (extern + entrée table)  
**development :** ajout `l_getbuttonstate` aussi + `_defer`, `_wnu`, `add_rule_once`, `run_timers`, `defer`, `is_network_up`, `when_network_up`, `arch`→`static_func`  
**Conflit :** `l_getbuttonstate` présent dans les deux — risque de **double entrée** dans la table. **Fusion : prendre la version dev (qui contient déjà `get_button_state`) et supprimer l'entrée scada dupliquée.**

---

### 🟡 Risque MODÉRÉ — zones différentes, relecture requise

#### `tasmota/tasmota_xdrv_driver/xdrv_52_3_berry_tasmota.ino`
**scada :** `l_getbuttonstate` (implémentation), fix typo `arvh`→`arch`, `WSContentSendRaw_P`, `SerialBridgeWrite`  
**development :** mêmes correctifs + `USE_TELNET` logging  
**Conflit :** correctifs identiques dans les deux branches. Dev est superset sauf l'implémentation de `l_getbuttonstate`. **Fusion : prendre dev + vérifier que `l_getbuttonstate` y est (c'est le cas via `be_tasmota_lib.c`).**

#### `tasmota/tasmota_xdrv_driver/xdrv_13_display.ino`
**scada :** `ApplyDisplayDimmer(uint8_t dimmer)`, `#define D_CMND_DISP_POWER`, `#define NUM_GRAPHS 4`  
**development :** mêmes changements `ApplyDisplayDimmer` + `jpeg_decoder.h`, `Power` dans réponse JSON  
**Conflit :** signature `ApplyDisplayDimmer` modifiée dans les deux. Dev est probablement l'upstream d'origine. **Vérifier les appels depuis scada.**

#### `tasmota/include/tasmota_version.h`
**scada :** `#define TASMOTA_BUILD 0x87` + historique custom (`0x80`…`0x87`)  
**development :** passage à v15.0.1.x, historique standard  
**Conflit :** même constante `TASMOTA_VERSION`. **Conserver la structure scada** (custom build + historique) en mettant à jour la base officielle.

#### `tasmota/my_user_config.h`
**scada :** active `USE_MCP23XXX_DRV`, reformate commentaires TM1638  
**development :** reformate les mêmes commentaires TM1638, ajoute USE_WIREGUARD, USE_TELNET, USE_XYZMODEM, USE_WEB_STATUS_LINE, USE_WIZMOTE  
**Conflit :** section TM1638 touchée des deux côtés. **Fusion manuelle requise sur cette section ; reste additionnel.**

---

### 🟢 Risque FAIBLE — zones indépendantes ou cosmétiques

| Fichier | Scada | Development | Évaluation |
|---|---|---|---|
| `tasmota/tasmota.ino` | types `power_t` pour leds | `skip_sleep`, `berry_deferred_ready`, safeboot, `SleepSkip()` | Zones différentes, fusion propre |
| `platformio.ini` | `monitor_filters` seulement | plateforme ESP8266 2025, `lib_ignore` audio | Sémantiquement indépendant |
| `.gitignore` | 7 entrées dont 3 communes avec dev | 3 entrées (subset de scada) | Fusion triviale : garder l'union |
| `tasmota/include/i18n.h` | `D_CMND_I2CSPEED` | nouveaux `D_SENSOR_xxx` GPIO | Zones différentes, pas de conflit |
| `.vscode/settings.json` | settings locaux | settings locaux | Garder scada |

---

## 4. Fichiers scada-exclusifs (aucun conflit)

| Fichier | Description |
|---|---|
| `tasmota/tasmota_support/support_button_v4.ino` | Gestion boutons avancée |
| `tasmota/tasmota_xdrv_driver/xdrv_66_tm1638.ino` | Driver TM1638 étendu |
| `tasmota/tasmota_xsns_sensor/xsns_05_esp32_ds18x20.ino` | DS18B20 disconnect/reconnect |
| `MYCONTRIB.md` | Doc contribution |
| `partitions/esp32_partition_app2880k_fs256k_safeboot896k.csv` | Partition custom |
| `partitions/partitions.md` | Doc partitions |
| `scripts/post_upload_to_syno.py` | Script post-build |

---

## 5. Risques d'incompatibilité fonctionnelle

### ⚠️ `GPIO_LED1_INV_OPENDRAIN` — décalage d'enum
Development insère de nouveaux GPIO dans l'enum avant `GPIO_SENSOR_END`. La valeur numérique de `GPIO_LED1_INV_OPENDRAIN` peut différer entre les deux branches → templates/configs flash mal interprétées si on upgraide le firmware sans re-flasher le template.  
**Action :** comparer les valeurs numériques dans les deux branches. La version dev fait référence.

### ⚠️ `support_a_i2c.ino` + `xdrv_67` — bus I2C et `CmndI2cSpeed`
Development refactorise entièrement la gestion I2C multi-bus. Scada a ajouté `default_frequency` et `CmndI2cSpeed` en surcouche de l'ancienne implémentation. Après merge, `CmndI2cSpeed` doit fonctionner avec la nouvelle structure `frequency[MAX_I2C]`.  
**Action :** réintégrer `default_frequency[]` + `force_default` dans la nouvelle structure ; vérifier que `CmndI2cSpeed` appelle bien `I2cSetClock()` avec les bons paramètres.

### ⚠️ `CmndLedPower` sans hook `FUNC_LED`
Si on prend la version dev sans réintégrer le dispatch `FUNC_LED`, les LEDs MCP23017 ne répondront plus aux commandes `LedPower`.  
**Action :** vérifier que la version mergée de `CmndLedPower` contient le bloc `XdrvCall(FUNC_LED)`.

### ✅ Nouveautés dev sans impact scada
Les gros ajouts (LoRaWAN, PN532, Hosted MCU, Telnet, Wireguard, Berry animation) sont tous sous `#ifdef USE_xxx` — aucun impact sur les fonctionnalités scada.

---

## 6. Plan de fusion incrémentale

> **Contexte réel** (vérifié sur development HEAD v15.4.0.2) :
> - `development` n'a **pas** encore `MAX_LEDS=32`, `FUNC_LED`, `led_power power_t`, `ledlnk_present` → scada est en avance sur ce point
> - `development` a le multi-bus I2C (`.bus` dans xdrv_67) et l'ODR interrupt → scada est en retard sur ce point
> - `development` n'a **pas** `get_button_state`, `default_frequency`, `CmndI2cSpeed` → scada exclusifs
> - Stratégie : créer une branche de travail `merge/dev-into-scada`, travailler par incrément, compiler + tester sur FIFG après chaque étape, puis merger dans `scada_projects`

---

### Préparation

```bash
git checkout scada_projects
git checkout -b merge/dev-into-scada
```

Chaque étape = un commit sur cette branche. Validation hardware avant de passer à la suivante.

---

### Étape 1 — Infrastructure de build (sans code fonctionnel)

**Fichiers :** `.gitignore`, `platformio.ini`, `.vscode/settings.json`, `BUILDS.md`, `CHANGELOG.md`

**Actions :**
- `.gitignore` : garder l'union des deux (scada a plus d'entrées)
- `platformio.ini` : prendre la version dev, réintégrer `monitor_filters = esp32_exception_decoder` et l'env `tasmota32-fifi` depuis `platformio_tasmota_cenv.ini`
- `.vscode/settings.json` : garder scada

**Compilation :** `pio run -e tasmota32-fifi` — doit compiler sans erreur  
**Test hardware :** aucun flash requis, c'est du build config  
**Commit :** `merge step 1/7: update build infra from development`

---

### Étape 2 — Types de base et headers (bloque tout le reste)

**Fichiers :** `tasmota/include/tasmota.h`, `tasmota/include/i18n.h`, `tasmota/tasmota.ino`

**Actions :**
- `tasmota.h` : prendre version dev comme base, y ajouter :
  - `MAX_LEDS = 32` (dev a encore 4)
  - `FUNC_LED` dans l'enum FUNC (dev a `FUNC_LED_LINK` mais pas `FUNC_LED`)
  - `led_power`/`led_inverted` en `power_t` (dev a encore `uint8_t`)
  - `ledlnk_present uint8_t` dans `TasmotaGlobal`
  - Conserver `FUNC_WEB_STATUS_LEFT/RIGHT`, macros SOC pour `MAX_I2S`/`MAX_RMT` (nouveautés dev)
- `i18n.h` : prendre version dev, réintégrer `D_CMND_I2CSPEED`
- `tasmota.ino` : prendre version dev (safeboot auto, `SleepSkip`) — les types `power_t` seront cohérents une fois `tasmota.h` fait

**Compilation :** doit passer (erreurs attendues sur les `.ino` qui référencent `led_power` avec l'ancien type → normales jusqu'à l'étape 4)  
**Test hardware :** flash + vérifier boot propre, log MQTT `Swimpool_info`, LEDs panneau FIFG-009-C  
**Commit :** `merge step 2/7: core types - MAX_LEDS=32, power_t leds, FUNC_LED`

---

### Étape 3 — Template GPIO

**Fichiers :** `tasmota/include/tasmota_template.h`

**Actions :**
- Prendre version dev comme base (elle inclut C8-CO2, V9240, LD2402, HSDIO, SDIO refactorisé)
- Vérifier la valeur numérique de `GPIO_LED1_INV_OPENDRAIN` dans les deux versions
  ```bash
  grep -n "GPIO_LED1_INV_OPENDRAIN\|GPIO_SENSOR_END" tasmota/include/tasmota_template.h
  git show development:tasmota/include/tasmota_template.h | grep -n "GPIO_LED1_INV_OPENDRAIN\|GPIO_SENSOR_END"
  ```
  ⚠️ Si la valeur a changé : mettre à jour le template flash du FIFG après le flash (WebUI → Configuration → Configure Other → Template)
- Réintégrer `AGPIO(GPIO_LED1_INV_OPENDRAIN)` dans la table de template si absent de dev

**Compilation :** `pio run -e tasmota32-fifi`  
**Test hardware :** flash + vérifier que les LEDs MCP23017 opendrain fonctionnent toujours  
**Commit :** `merge step 3/7: tasmota_template.h - GPIO_LED1_INV_OPENDRAIN + new GPIOs from dev`

---

### Étape 4 — Driver I2C + xdrv_67 MCP23017

**Fichiers :** `tasmota/tasmota_support/support_a_i2c.ino`, `tasmota/tasmota_xdrv_driver/xdrv_67_mcp23xxx.ino`

**Actions :**

`support_a_i2c.ino` — prendre version dev (multi-bus, `MAX_I2C`, refactoring complet), puis réintégrer :
- `default_frequency[MAX_I2C]` dans la struct `I2C`
- Paramètre `force_default` dans `I2cSetClock()`
- Logique de restauration depuis `default_frequency` (au lieu de hardcoder 100 kHz)
- Log `using freq=xxx Hz` dans la réponse

`xdrv_67_mcp23xxx.ino` — prendre version dev (multi-bus `.bus`, ODR interrupt fixes) comme base, puis réintégrer depuis scada :
- Support LEDs (`FUNC_LED`, `FUNC_LED_LINK`) — mapping LEDs MCP23017
- Support LedLnk
- Topology support
- `get_button_state` callback
- Gestion opendrain pour les LEDs (distincte de l'ODR interrupt déjà dans dev)

**Compilation :** `pio run -e tasmota32-fifi`  
**Test hardware (le plus important) :**
- Flash + boot propre
- Vérifier I2C : `i2cScan` → MCP23017 détecté à la bonne adresse
- `i2cSpeed 400000` → fréquence effective vérifiée dans les logs
- LEDs panneau FIFG-009-C répondent aux commandes `LedPower`
- Boutons physiques (SINGLE + HOLD) fonctionnels
- Topology : plusieurs MCP23017 si disponibles

**Commit :** `merge step 4/7: I2C multi-bus + xdrv_67 LEDs/topology from dev`

---

### Étape 5 — support_command + support_tasmota (LED + I2cSpeed)

**Fichiers :** `tasmota/tasmota_support/support_command.ino`, `tasmota/tasmota_support/support_tasmota.ino`

**Actions :**

`support_command.ino` — prendre version dev, réintégrer :
- `CmndI2cSpeed` (commande + entrée table de dispatch)
- `D_CMND_I2CSPEED` dans la liste des commandes
- Dans `CmndLedPower` : bloc `XdrvCall(FUNC_LED)` pour déléguer aux drivers externes (MCP23017)
- Réponse JSON enrichie `LEDLNK`/`LEDS`

`support_tasmota.ino` — prendre version dev, réintégrer :
- Hook `FUNC_LED` dans `SetLedPowerIdx()` (dispatch vers xdrv quand pas de GPIO natif)
- Refactoring `UpdateLedPower()` sans mode legacy LedLnk

**Compilation :** `pio run -e tasmota32-fifi`  
**Test hardware :**
- Flash + boot propre
- `LedPower1 1/0` → LED 1 MCP23017 répond
- `i2cSpeed 400000` → log + fréquence persistée via `default_frequency`
- Commande `i2cSpeed` sans argument → retourne la fréquence courante

**Commit :** `merge step 5/7: support_command + support_tasmota - FUNC_LED hook, CmndI2cSpeed`

---

### Étape 6 — Berry

**Fichiers :** `lib/libesp32/berry_tasmota/src/be_tasmota_lib.c`, `tasmota/tasmota_xdrv_driver/xdrv_52_3_berry_tasmota.ino`

**Actions :**

`be_tasmota_lib.c` — prendre version dev (nouvelles closures `defer`, `when_network_up`…), vérifier que `get_button_state` y est déjà :
```bash
git show development:lib/libesp32/berry_tasmota/src/be_tasmota_lib.c | grep get_button_state
```
→ Si absent : réintégrer `extern l_getbuttonstate` + entrée table. Si présent : ne rien faire (éviter le doublon)

`xdrv_52_3_berry_tasmota.ino` — prendre version dev, vérifier :
- `l_getbuttonstate` implémentation présente (sinon réintégrer depuis scada)
- `USE_TELNET` logging déjà dans dev → garder

**Compilation :** `pio run -e tasmota32-fifi`  
**Test hardware :**
- Flash + boot propre
- Console Berry : `tasmota.get_button_state(0)` → retourne 0 ou 1 selon état bouton
- `tasmota.defer(def() print('ok') end)` → fonctionne (nouvelle API dev)

**Commit :** `merge step 6/7: Berry - get_button_state, defer, when_network_up`

---

### Étape 7 — Display, config, version

**Fichiers :** `tasmota/tasmota_xdrv_driver/xdrv_13_display.ino`, `tasmota/my_user_config.h`, `tasmota/include/tasmota_version.h`

**Actions :**

`xdrv_13_display.ino` — prendre version dev (`jpeg_decoder.h`, `Power` dans JSON), vérifier que la signature `ApplyDisplayDimmer(uint8_t dimmer)` est cohérente avec scada

`my_user_config.h` — prendre version dev, réintégrer :
- `#define USE_MCP23XXX_DRV` activé (dev l'a en commentaire)
- Paramètres TM1638 actifs de scada (vérifier section par section)

`tasmota_version.h` — conserver la structure scada :
```cpp
#define TASMOTA_BUILD  0x88   // prochaine version custom
// Mettre à jour le commentaire historique avec 0x88 et sa description
const uint32_t TASMOTA_VERSION = 0x0F040000 + TASMOTA_BUILD;  // base dev 15.4.0
```

**Compilation :** `pio run -e tasmota32-fifi`  
**Test hardware :**
- Flash complet + boot propre
- Vérifier la version affichée dans l'UI Tasmota
- Test fonctionnel complet : pompe, LEDs, boutons, pH/ORP, DS18B20, HASS

**Commit :** `merge step 7/7: display, user_config, version - complete merge`

---

### Finalisation

```bash
git checkout scada_projects
git merge --no-ff merge/dev-into-scada -m "Merge development v15.4.0 into scada_projects"
git branch -d merge/dev-into-scada
```
