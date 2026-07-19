"""Portable application roots for development and frozen (PyInstaller) runs.

User-writable data always resolves next to the executable when frozen, never
under the read-only ``sys._MEIPASS`` bundle tree. Bundle/read-only resources
(if any) use the resource root.
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import Optional

# Overridable for tests and packaging metadata.
__version__ = "0.0.0+dev"


def is_frozen() -> bool:
    """Return True when running inside a PyInstaller (or similar) bundle."""
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def get_resource_root() -> str:
    """Read-only root: source tree in dev, ``_MEIPASS`` when frozen."""
    meipass = getattr(sys, "_MEIPASS", None)
    if is_frozen() and meipass:
        return os.path.abspath(str(meipass))
    return os.path.dirname(os.path.abspath(__file__))


def get_app_root() -> str:
    """User-writable application root.

    - Development: directory containing this module (repo / source root).
    - Frozen one-dir / one-file: directory containing the executable.
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def user_path(*parts: str) -> str:
    """Join path segments under the writable application root."""
    return os.path.join(get_app_root(), *parts)


def resource_path(*parts: str) -> str:
    """Join path segments under the read-only resource root."""
    return os.path.join(get_resource_root(), *parts)


def ensure_user_data_layout(copy_example: bool = True) -> str:
    """Ensure writable app root exists and seed ``config.example.json`` if needed.

    Does not create or overwrite a real ``config.json`` (that may hold secrets).
    Returns the app root path.
    """
    root = get_app_root()
    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        pass

    if copy_example:
        dest = os.path.join(root, "config.example.json")
        if not os.path.isfile(dest):
            candidates = [
                resource_path("config.example.json"),
                # one-dir layouts sometimes keep extras next to the exe already
                os.path.join(root, "config.example.json"),
            ]
            for src in candidates:
                if os.path.isfile(src) and os.path.normcase(os.path.abspath(src)) != os.path.normcase(
                    os.path.abspath(dest)
                ):
                    try:
                        shutil.copy2(src, dest)
                    except OSError:
                        pass
                    break
    return root


def default_config_path() -> str:
    return user_path("config.json")


def default_accounts_path(timestamp: str) -> str:
    return user_path(f"accounts_{timestamp}.txt")


def default_token_path() -> str:
    return user_path("token.json")


def default_cpa_auth_dir() -> str:
    return user_path("cpa_auths")


def default_mail_credentials_dir() -> str:
    return get_app_root()


def program_name() -> str:
    """Human-facing binary / script name for help text."""
    if is_frozen():
        return os.path.basename(sys.executable)
    return "python grok_register_ttk.py"


def resolve_version(cli_override: Optional[str] = None) -> str:
    if cli_override:
        return cli_override
    env = os.environ.get("GROK_REGISTER_VERSION", "").strip()
    if env:
        return env
    return __version__
