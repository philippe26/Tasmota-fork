import os
import json
import tempfile
import re
from shutil import copyfile
from pathlib import Path
Import("env")

# === CONFIGURATION ===
SYNOLOGY_HOST     = "syno"
SYNOLOGY_USER     = "admin"
SYNOLOGY_DEST_DIR = "/volume1/web/ota"

# === Helpers ===
def get_project_dir():
    return env.subst("$PROJECT_DIR")

def get_tasmota_version():
    header = os.path.join(get_project_dir(), "tasmota/include/tasmota_version.h")
    try:
        base    = None
        build   = None
        with open(header, "r") as f:
            for line in f:
                # Extrait TASMOTA_BUILD 0x84
                m = re.match(r'#define\s+TASMOTA_BUILD\s+(0x[0-9A-Fa-f]+|\d+)', line)
                if m:
                    build = int(m.group(1), 0)

                # Extrait la base 0x0E040100
                m = re.match(r'.*TASMOTA_VERSION\s*=\s*(0x[0-9A-Fa-f]+)\s*\+', line)
                if m:
                    base = int(m.group(1), 0)

        if base is not None and build is not None:
            version = base + build
            major  = (version >> 24) & 0xFF
            minor  = (version >> 16) & 0xFF
            patch  = (version >>  8) & 0xFF
            build_ =  version        & 0xFF
            return f"{major}.{minor}.{patch}.{build_}"

    except Exception as e:
        print(f"[WARN] Impossible de lire la version: {e}")
    return "unknown"


def scp_upload(local_path, remote_path):
    cmd = f"scp {local_path} {SYNOLOGY_USER}@{SYNOLOGY_HOST}:{remote_path}"
    print(f"[INFO] {cmd}")
    ret = os.system(cmd)
    if ret != 0:
        raise RuntimeError(f"SCP échoué (code {ret}) : {cmd}")

def rsync_upload(local_path, remote_path):
    remote_dir = os.path.dirname(remote_path)
    
    # Crée le dossier distant si nécessaire
    os.system(f"ssh {SYNOLOGY_USER}@{SYNOLOGY_HOST} 'mkdir -p {remote_dir}'")
    
    cmd = f"rsync -av {local_path} {SYNOLOGY_USER}@{SYNOLOGY_HOST}:{remote_path}"
    print(f"[INFO] {cmd}")
    ret = os.system(cmd)
    if ret != 0:
        raise RuntimeError(f"rsync échoué (code {ret}) : {cmd}")
    
# === Post-build ===
def after_build(source, target, env):
    env_name      = env['PIOENV']
    firmware_name = f"{env_name}.bin"
    tmp_dir       = Path(tempfile.gettempdir())

    # 1. Copie locale du binaire
    firmware_src  = target[0].get_abspath()
    firmware_tmp  = tmp_dir / firmware_name
    print(f"[INFO] Copie locale → {firmware_tmp}")
    copyfile(firmware_src, firmware_tmp)

    # 2. Extraction de version
    version = get_tasmota_version()
    print(f"[INFO] Version : {version}")

    # 3. Génération manifest par env
    manifest_name = f"{env_name}_manifest.json"
    manifest_tmp  = tmp_dir / manifest_name
    manifest = {
        "version": version,
        "env":     env_name,
        "url":     f"http://{SYNOLOGY_HOST}/ota/{firmware_name}"
    }
    with open(manifest_tmp, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"[INFO] Manifest : {manifest_tmp}")

    # 4. Upload SCP
    print("[INFO] Upload vers Synology...")
    try:
        rsync_upload(firmware_tmp, f"{SYNOLOGY_DEST_DIR}/{firmware_name}")
        rsync_upload(manifest_tmp, f"{SYNOLOGY_DEST_DIR}/{manifest_name}")
        print(f"[OK] Upload terminé → http://{SYNOLOGY_HOST}/ota/{firmware_name}\n")
    except RuntimeError as e:
        print(f"[ERROR] {e}\n")

env.AddPostAction("$BUILD_DIR/${PROGNAME}.bin", after_build)
