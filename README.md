<div align="center">

# 🛡️ JayVPN

**A lightweight Windows VPN client powered by the Webshare.io proxy API**

![Platform](https://img.shields.io/badge/platform-Windows-blue?style=flat-square&logo=windows)
![Python](https://img.shields.io/badge/python-3.8%2B-blue?style=flat-square&logo=python)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

</div>

---

## 📋 Table of Contents

- [Getting Started](#getting-started)
- [Build Instructions](#build-instructions)
- [Refresh Icon Cache](#refresh-icon-cache)
- [Uninstall / Clean Registry](#uninstall--clean-registry)
- [Required Files](#required-files)
- [Notes](#notes)

---

## Getting Started

### Step 1 — Create a Webshare.io Account & Get Your API Key

Before using JayVPN, you need a proxy API key from [webshare.io](https://webshare.io).

1. Go to **[webshare.io](https://webshare.io)** and click **Sign Up**
2. Create a free or paid account
3. Navigate to **Dashboard → API** and copy your API key
4. Enter this key inside JayVPN on first launch

> **Where is the key stored?**  
> JayVPN saves your API key securely in the Windows Registry at:  
> `HKEY_CURRENT_USER\Software\JayVPN`

---

## Build Instructions

### Step 2 — Build Single `.EXE` with PyInstaller

Run the following command from your **project folder** to compile JayVPN into a single portable executable.

```bash
python -m PyInstaller --noconfirm --onefile --windowed \
  --icon=256x256.ico \
  --name=JayVPN \
  --add-data "256x256.ico;." \
  --add-data "icon.ico;." \
  --add-data "logo.png;." \
  --add-data "chrome.png;." \
  --add-data "usa.png;." \
  --add-data "uk.png;." \
  --add-data "ger.png;." \
  --add-data "jp.png;." \
  --add-data "settings.png;." \
  --add-data "online.png;." \
  --add-data "offline.png;." \
  --hidden-import pystray \
  --hidden-import pystray._win32 \
  main.py
```

> ✅ After the build finishes, **`JayVPN.exe`** will be located in the **`dist/`** folder.

---

## Refresh Icon Cache

### Step 3 — Fix Broken Icons on Windows

If the JayVPN taskbar or desktop icon displays incorrectly after installation, run this command in **Command Prompt** to flush the icon cache and restart Explorer:

```cmd
cmd /c "taskkill /f /im explorer.exe & del /f /q "%localappdata%\IconCache.db" & del /f /q "%localappdata%\Microsoft\Windows\Explorer\iconcache_*.db" & start explorer.exe"
```

> No administrator privileges required.

---

## Uninstall / Clean Registry

### Step 4 — Remove JayVPN Registry Entries

JayVPN stores its API key in the Windows Registry. Use either method below to remove it completely.

#### Method A — `.reg` File *(Recommended)*

Create a file named `remove_jayvpn_registry.reg` with the following content, then **double-click it** and confirm the prompt:

```reg
Windows Registry Editor Version 5.00

[-HKEY_CURRENT_USER\Software\JayVPN]
```

#### Method B — Command Prompt

```cmd
reg delete "HKEY_CURRENT_USER\Software\JayVPN" /f
```

#### Verify Removal

Open **`regedit`** → `HKEY_CURRENT_USER` → `Software` and confirm **JayVPN** is no longer listed.

---

## Required Files

Make sure all of the following files are present in your project folder before running the build command:

| File | Description |
|------|-------------|
| `main.py` | Main application entry point |
| `256x256.ico` | Application icon (256×256) |
| `icon.ico` | Application tray icon |
| `logo.png` | App logo |
| `chrome.png` | Chrome browser asset |
| `usa.png` | US server flag |
| `uk.png` | UK server flag |
| `ger.png` | Germany server flag |
| `jp.png` | Japan server flag |
| `settings.png` | Settings icon |
| `online.png` | Online status icon |
| `offline.png` | Offline status icon |

---

## Notes

- 🔑 The API key is saved in the **Windows Registry**, not as an external file.
- 📦 The output executable (`JayVPN.exe`) will be inside the **`dist/`** folder after building.
- 🖥️ JayVPN is a **Windows-only** application.

---

<div align="center">
  <sub>Built with Python</sub>
</div>
