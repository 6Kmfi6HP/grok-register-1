# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for grok-register (one-dir distribution).

Prefer one-dir over one-file so native/browser-adjacent libraries and data
files remain on a normal filesystem tree. User data (config, accounts, CPA
auths) is written next to the executable via app_paths.get_app_root().

Browser strategy: use system Chrome/Chromium via CloakBrowser/Playwright.
Do not bundle a full browser binary (size + licensing + reliability).
"""
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Hidden / dynamic imports that PyInstaller often misses.
hiddenimports = [
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
    "tkinter.scrolledtext",
    "filelock",
    "psutil",
    "certifi",
    "curl_cffi",
    "cloakbrowser",
    "cpa_xai",
    "cpa_xai.mint",
    "cpa_xai.oauth_device",
    "cpa_xai.browser_session",
    "cpa_xai.browser_confirm",
    "cpa_xai.proxyutil",
    "cpa_xai.schema",
    "cpa_xai.writer",
    "app_paths",
    "app_config",
    "account_outputs",
    "browser_runtime",
    "browser_adapter",
    "mail_service",
    "registration_browser",
    "registration_flow",
    "cpa_export",
    "tab_pool",
]

datas = []
binaries = []

# Collect CloakBrowser / Playwright-related package data when available.
for pkg in ("cloakbrowser", "curl_cffi", "certifi"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception as exc:  # pragma: no cover - build-time only
        print(f"[spec] collect_all({pkg}) skipped: {exc}", file=sys.stderr)

try:
    hiddenimports += collect_submodules("cpa_xai")
except Exception as exc:  # pragma: no cover
    print(f"[spec] collect_submodules(cpa_xai) skipped: {exc}", file=sys.stderr)

# Ship clean config template inside the bundle (also copied next to exe by build scripts).
if os.path.isfile("config.example.json"):
    datas.append(("config.example.json", "."))

# Optional extension directory if present in the source tree.
if os.path.isdir("turnstilePatch"):
    datas.append(("turnstilePatch", "turnstilePatch"))

# Banner asset is optional for packaged CLI; include if present.
if os.path.isfile(os.path.join("assets", "banner.png")):
    datas.append((os.path.join("assets", "banner.png"), "assets"))

# Explicitly exclude secrets / user data from analysis and bundle.
excludes = [
    # heavy / unused
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "PIL",
    "IPython",
    "notebook",
    "pytest",
]

a = Analysis(
    ["grok_register_ttk.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Drop any accidentally collected secret / user files by path name.
_SECRET_BASENAMES = {
    "config.json",
    "mail_credentials.txt",
    "token.json",
    "cpa_auth_failed.txt",
}
_SECRET_PREFIXES = ("accounts_",)
_SECRET_DIR_MARKERS = (os.sep + "cpa_auths" + os.sep, "/cpa_auths/", "\\cpa_auths\\")


def _is_secret_path(path):
    name = os.path.basename(str(path))
    if name in _SECRET_BASENAMES:
        return True
    if name.startswith(_SECRET_PREFIXES) and name.endswith(".txt"):
        return True
    if name.endswith(".pending.jsonl"):
        return True
    lowered = str(path).replace("/", os.sep)
    for marker in _SECRET_DIR_MARKERS:
        if marker in lowered or lowered.endswith(os.sep + "cpa_auths"):
            return True
    return False


a.datas = [entry for entry in a.datas if not _is_secret_path(entry[0] if isinstance(entry, (list, tuple)) else entry)]
a.binaries = [entry for entry in a.binaries if not _is_secret_path(entry[0] if isinstance(entry, (list, tuple)) else entry)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Windows: windowed binary so double-click does not flash a console.
# Non-Windows: console=True so CLI --help/--version work cleanly in CI/terminals.
# CLI args (cli/start/retry-pending) remain available on all platforms.
_is_windows = sys.platform.startswith("win")
_console = not _is_windows

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="grok-register",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=_console,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="grok-register",
)
