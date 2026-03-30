import os
import subprocess
import sys
import json
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error

OS_ID = "57"   # Windows 10 64-bit
LANG  = "1033" # English


def run_capture(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def run_live(cmd):
    try:
        r = subprocess.run(cmd, shell=True)
        return r.returncode
    except Exception as e:
        print(f"[ERROR] {e}")
        return -1


def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        print(f"[ERROR] Cannot reach NVIDIA API ({e.reason}). Check internet.")
        return None
    except Exception as e:
        print(f"[ERROR] Network error: {e}")
        return None


# ── GeForce Experience ────────────────────────────────────────────────────────

def check_winget():
    code, _, _ = run_capture("winget --version")
    if code != 0:
        print("[ERROR] winget not found. Install 'App Installer' from Microsoft Store.")
        sys.exit(1)


def check_gfe():
    print("\n[GFE] Checking GeForce Experience...")
    code, out, _ = run_capture(
        "winget list --id Nvidia.GeForceExperience --accept-source-agreements"
    )
    installed = "Nvidia.GeForceExperience" in out or "GeForce Experience" in out

    if not installed:
        print("[GFE] Not installed. Launching installer...")
        code = run_live(
            "winget install --id Nvidia.GeForceExperience "
            "--accept-package-agreements --accept-source-agreements"
        )
        if code == 0:
            print("[GFE] Installation complete.")
        else:
            print(f"[ERROR] GFE installation failed (exit {code}).")
    else:
        print("[GFE] Installed. Checking for updates...")
        code = run_live(
            "winget upgrade --id Nvidia.GeForceExperience "
            "--accept-package-agreements --accept-source-agreements"
        )
        if code != 0:
            print(f"[WARN] GFE upgrade exited with code {code}. May already be up to date.")


# ── Driver check ──────────────────────────────────────────────────────────────

def get_installed_driver():
    smi_args = "--query-gpu=name,driver_version --format=csv,noheader"
    code, out, _ = run_capture(f"nvidia-smi {smi_args}")
    if code != 0 or not out.strip():
        # Fallback: NVSMI folder not always in PATH
        fallback = os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe"
        )
        code, out, _ = run_capture(f'"{fallback}" {smi_args}')
    if code != 0 or not out.strip():
        print("[ERROR] nvidia-smi not found. Is an NVIDIA GPU installed?")
        return None, None
    parts = [p.strip() for p in out.strip().split("\n")[0].split(",")]
    if len(parts) < 2:
        print("[ERROR] Unexpected nvidia-smi output.")
        return None, None
    return parts[0], parts[1]


def find_pfid(gpu_name):
    xml_data = fetch(
        "https://www.nvidia.com/Download/API/lookupValueSearch.aspx?TypeID=9"
    )
    if not xml_data:
        return None

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        print(f"[ERROR] Failed to parse NVIDIA series XML: {e}")
        return None

    gpu_up = gpu_name.upper().replace("NVIDIA ", "")
    is_laptop = "LAPTOP" in gpu_up or "NOTEBOOK" in gpu_up

    # Dynamically match GPU name against all series in the NVIDIA catalog
    best_psid  = None
    best_score = 0

    for item in root.iter("LookupValue"):
        series_name = (item.findtext("Name") or "").upper()
        series_val  = item.findtext("Value") or ""

        # Strip noise words to get the core identifier (e.g. "RTX 30")
        core = (series_name
                .replace("GEFORCE ", "")
                .replace(" SERIES", "")
                .replace("(DESKTOP)", "")
                .replace("(NOTEBOOKS)", "")
                .replace("(NOTEBOOK)", "")
                .strip())

        if not core or core not in gpu_up:
            continue

        is_nb_series = "NOTEBOOK" in series_name or "LAPTOP" in series_name
        type_bonus   = 10 if (is_laptop == is_nb_series) else 0
        score        = len(core) + type_bonus

        if score > best_score:
            best_score = score
            best_psid  = series_val

    if not best_psid or not best_psid.strip().isdigit():
        print(f"[WARN] Could not map '{gpu_name}' to a valid series in the NVIDIA catalog.")
        return None

    xml_data2 = fetch(
        f"https://www.nvidia.com/Download/API/lookupValueSearch.aspx?TypeID=8&ParentID={best_psid}"
    )
    if not xml_data2:
        return None

    try:
        root2 = ET.fromstring(xml_data2)
    except ET.ParseError:
        return None

    gpu_clean = gpu_name.replace("NVIDIA ", "").strip().upper()
    first_val = None
    for item in root2.iter("LookupValue"):
        name = (item.findtext("Name") or "").upper()
        val  = item.findtext("Value") or ""
        if first_val is None:
            first_val = val
        if gpu_clean in name or name in gpu_clean:
            return val

    return first_val  # fallback: first family in series


def check_driver():
    print("\n[DRIVER] Checking NVIDIA Studio Driver...")
    gpu_name, installed_ver = get_installed_driver()
    if not gpu_name:
        return

    print(f"[DRIVER] GPU      : {gpu_name}")
    print(f"[DRIVER] Installed: {installed_ver}")

    pfid = find_pfid(gpu_name)
    if not pfid:
        print("[WARN] Skipping online version check.")
        return

    url = (
        "https://gfwsl.geforce.com/services_toolkit/services/com/nvidia/services/"
        f"AjaxDriverService.php?func=DriverManualLookup"
        f"&pfid={pfid}&osID={OS_ID}&languageCode={LANG}&isWHQL=1&dch=1&dtcid=5"
    )
    data = fetch(url)
    if not data:
        return

    try:
        j = json.loads(data)
        latest_ver = j["IDS"][0]["downloadInfo"]["Version"]
    except (KeyError, IndexError, json.JSONDecodeError, TypeError):
        print("[ERROR] Could not parse driver version from NVIDIA API.")
        return

    if installed_ver.strip() == latest_ver.strip():
        print(f"[DRIVER] Latest   : {latest_ver} → UP TO DATE")
    else:
        print(f"[DRIVER] Latest   : {latest_ver} → UPDATE AVAILABLE")
        print("[DRIVER] Download : https://www.nvidia.com/en-us/drivers/")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    check_winget()
    check_gfe()
    check_driver()
    print("\nDone.")
