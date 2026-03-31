import os
import re
import subprocess
import sys
import json
import tempfile
import urllib.request
import urllib.error

OS_ID = "57"   # Windows 10 64-bit
LANG  = "1033" # English


def run_capture(cmd, timeout=60):
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -2, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def run_live(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, timeout=timeout)
        return r.returncode
    except subprocess.TimeoutExpired:
        print("[WARN] Command timed out.")
        return -2
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


def open_driver_update_ui():
    # If API lookup fails, send user directly to NVIDIA App driver section.
    code = run_live('start "" "nvidiaapp://drivers"', timeout=10)
    if code == 0:
        print("[DRIVER] Opened NVIDIA App driver section.")
    else:
        print("[DRIVER] Could not open NVIDIA App URI. Opening NVIDIA drivers webpage...")
        run_live('start "" "https://www.nvidia.com/en-us/drivers/"', timeout=10)


def parse_lookup_values(raw_text):
    # NVIDIA lookup endpoints sometimes return malformed XML; regex parsing is more tolerant.
    items = []
    for block in re.findall(r"<LookupValue>(.*?)</LookupValue>", raw_text, flags=re.S | re.I):
        name_m = re.search(r"<Name>(.*?)</Name>", block, flags=re.S | re.I)
        value_m = re.search(r"<Value>(.*?)</Value>", block, flags=re.S | re.I)
        if not name_m or not value_m:
            continue
        name = re.sub(r"\s+", " ", name_m.group(1)).strip()
        value = value_m.group(1).strip()
        if name and value:
            items.append((name, value))
    return items


def parse_version(v):
    nums = [int(x) for x in re.findall(r"\d+", v or "")]
    return tuple(nums)


def is_version_newer(installed, latest):
    return parse_version(latest) > parse_version(installed)


# ── GeForce Experience ────────────────────────────────────────────────────────

def has_winget():
    code, _, _ = run_capture("winget --version")
    return code == 0


def check_gfe():
    print("\n[GFE] Checking GeForce Experience...")
    ids = ["NVIDIA.GeForceExperience", "Nvidia.GeForceExperience"]
    base_args = "--accept-package-agreements --accept-source-agreements --disable-interactivity"

    # Try upgrade first; if package exists and is installed this handles pending updates directly.
    for pkg_id in ids:
        code = run_live(f"winget upgrade --id {pkg_id} {base_args}", timeout=180)
        if code == 0:
            print(f"[GFE] Upgrade/install check completed for {pkg_id}.")
            return

    print("[GFE] Upgrade path not available. Trying fresh install...")
    for pkg_id in ids:
        code = run_live(f"winget install --id {pkg_id} {base_args}", timeout=180)
        if code == 0:
            print(f"[GFE] Installation completed for {pkg_id}.")
            return

    print("[WARN] Could not install/update GeForce Experience via winget on this machine.")


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

    series_items = parse_lookup_values(xml_data)
    if not series_items:
        print("[ERROR] Could not parse NVIDIA series catalog response.")
        return None

    gpu_up = gpu_name.upper().replace("NVIDIA ", "")
    is_laptop = "LAPTOP" in gpu_up or "NOTEBOOK" in gpu_up

    # Dynamically match GPU name against all series in the NVIDIA catalog
    best_psid  = None
    best_score = 0

    for series_name_raw, series_val in series_items:
        series_name = series_name_raw.upper()

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

    family_items = parse_lookup_values(xml_data2)
    if not family_items:
        return None

    gpu_clean = gpu_name.replace("NVIDIA ", "").strip().upper()
    first_val = None
    for name_raw, val in family_items:
        name = name_raw.upper()
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
        print("[WARN] Could not resolve exact Studio package via API.")
        print("[DRIVER] Continuing with NVIDIA App direct update flow.")
        open_driver_update_ui()
        return

    url = (
        "https://gfwsl.geforce.com/services_toolkit/services/com/nvidia/services/"
        f"AjaxDriverService.php?func=DriverManualLookup"
        f"&pfid={pfid}&osID={OS_ID}&languageCode={LANG}&isWHQL=1&dch=1&dtcid=5"
    )
    data = fetch(url)
    if not data:
        print("[DRIVER] API unavailable. Continuing with NVIDIA App direct update flow.")
        open_driver_update_ui()
        return

    try:
        j = json.loads(data)
        info = j["IDS"][0]["downloadInfo"]
        latest_ver = info["Version"]
        download_url = (
            info.get("DownloadURL")
            or info.get("downloadURL")
            or info.get("DownloadURLFile")
            or info.get("downloadURLFile")
        )
    except (KeyError, IndexError, json.JSONDecodeError, TypeError):
        print("[ERROR] Could not parse driver version from NVIDIA API.")
        print("[DRIVER] Continuing with NVIDIA App direct update flow.")
        open_driver_update_ui()
        return

    if not is_version_newer(installed_ver, latest_ver):
        print(f"[DRIVER] Latest   : {latest_ver} → UP TO DATE")
    else:
        print(f"[DRIVER] Latest   : {latest_ver} → UPDATE AVAILABLE")
        if not download_url:
            print("[DRIVER] Download : https://www.nvidia.com/en-us/drivers/")
            print("[WARN] Download URL not returned by API. Install manually from link above.")
            return

        installer_path = os.path.join(tempfile.gettempdir(), f"nvidia_studio_{latest_ver}.exe")
        print("[DRIVER] Downloading installer...")
        try:
            urllib.request.urlretrieve(download_url, installer_path)
        except Exception as e:
            print(f"[ERROR] Failed to download Studio Driver: {e}")
            print("[DRIVER] Continuing with NVIDIA App direct update flow.")
            open_driver_update_ui()
            return

        print("[DRIVER] Launching installer (UI)...")
        code = run_live(f'"{installer_path}"')
        if code == 0:
            print("[DRIVER] Installer finished.")
        else:
            print(f"[WARN] Installer exited with code {code}. Please verify in NVIDIA App/GFE.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if has_winget():
        check_gfe()
    else:
        print("[WARN] winget not found. Skipping GeForce Experience step.")
    check_driver()
    print("\nDone.")
