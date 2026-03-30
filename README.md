# nvidia_updater

Checks and installs GeForce Experience and compares your installed NVIDIA Studio Driver against the latest available version. No login required.

## Requirements

- Windows 10 64-bit
- Python 3.x — https://python.org
- Internet connection

## Usage

Double-click **`update_nvidia.bat`** (a UAC prompt will appear if not already admin).

The script will:
1. Check if GeForce Experience is installed — installs or updates it via winget.
2. Read your current NVIDIA driver version via `nvidia-smi`.
3. Query NVIDIA's public API for the latest Studio Driver and report the result.

## Output example

```
[GFE] Installed. Checking for updates...
...
[DRIVER] GPU      : NVIDIA GeForce RTX 4070
[DRIVER] Installed: 572.83
[DRIVER] Latest   : 575.51 → UPDATE AVAILABLE
[DRIVER] Download : https://www.nvidia.com/en-us/drivers/
```
