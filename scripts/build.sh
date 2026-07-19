#!/usr/bin/env bash
# Build a one-dir grok-register package with PyInstaller.
# Usage:
#   ./scripts/build.sh [version]
#   GROK_REGISTER_VERSION=v1.0.0 ./scripts/build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${1:-${GROK_REGISTER_VERSION:-dev}}"
VERSION="${VERSION#v}"
OS_NAME="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) ARCH_LABEL="x64" ;;
  arm64|aarch64) ARCH_LABEL="arm64" ;;
  *) ARCH_LABEL="$ARCH" ;;
esac
case "$OS_NAME" in
  darwin) PLATFORM="macos" ;;
  linux) PLATFORM="linux" ;;
  msys*|mingw*|cygwin*) PLATFORM="windows" ;;
  *) PLATFORM="$OS_NAME" ;;
esac

# Prefer explicit PYTHON, then active venv, then python3/python.
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    PYTHON="${VIRTUAL_ENV}/bin/python"
  elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
  else
    PYTHON=python
  fi
fi

echo "[build] version=$VERSION platform=$PLATFORM arch=$ARCH_LABEL"
echo "[build] python=$PYTHON ($("$PYTHON" -c 'import sys; print(sys.version.split()[0])'))"

"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r requirements.txt
"$PYTHON" -m pip install "pyinstaller>=6.0,<7"

# Stamp version into app_paths for --version (restored after freeze so git stays clean).
export GROK_REGISTER_VERSION="v${VERSION}"
APP_PATHS_BACKUP=""
if [[ -f app_paths.py ]]; then
  APP_PATHS_BACKUP="$(mktemp)"
  cp app_paths.py "$APP_PATHS_BACKUP"
  "$PYTHON" - <<PY
from pathlib import Path
path = Path("app_paths.py")
text = path.read_text(encoding="utf-8")
old = '__version__ = "0.0.0+dev"'
new = '__version__ = "v${VERSION}"'
if old in text:
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("[build] stamped version v${VERSION}")
else:
    print("[build] version stamp skipped (pattern not found)")
PY
fi

restore_app_paths() {
  if [[ -n "${APP_PATHS_BACKUP}" && -f "${APP_PATHS_BACKUP}" ]]; then
    cp "$APP_PATHS_BACKUP" app_paths.py
    rm -f "$APP_PATHS_BACKUP"
    echo "[build] restored app_paths.py"
  fi
}
trap restore_app_paths EXIT

rm -rf build dist
# Spec chooses console=True on non-Windows, windowed on Windows.
"$PYTHON" -m PyInstaller --noconfirm --clean grok-register.spec
restore_app_paths
trap - EXIT

APP_DIR="dist/grok-register"
if [[ ! -d "$APP_DIR" ]]; then
  echo "[build] ERROR: expected one-dir output at $APP_DIR" >&2
  ls -la dist || true
  exit 1
fi

# Place clean config template next to the executable (user-writable root).
if [[ -f config.example.json ]]; then
  cp -f config.example.json "$APP_DIR/config.example.json"
fi

# Optional start helpers
if [[ "$PLATFORM" == "macos" || "$PLATFORM" == "linux" ]]; then
  cat > "$APP_DIR/run-gui.sh" <<'EOF'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/grok-register" "$@"
EOF
  cat > "$APP_DIR/run-cli.sh" <<'EOF'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/grok-register" cli "$@"
EOF
  chmod +x "$APP_DIR/run-gui.sh" "$APP_DIR/run-cli.sh" "$APP_DIR/grok-register" || true
fi

# Sanity: no secret user files inside the tree
if [[ -f "$APP_DIR/config.json" ]]; then
  echo "[build] ERROR: secret config.json must not be bundled" >&2
  exit 1
fi
if ls "$APP_DIR"/accounts_*.txt >/dev/null 2>&1; then
  echo "[build] ERROR: accounts_*.txt must not be bundled" >&2
  exit 1
fi
if [[ -d "$APP_DIR/cpa_auths" ]] && [[ -n "$(ls -A "$APP_DIR/cpa_auths" 2>/dev/null || true)" ]]; then
  echo "[build] ERROR: non-empty cpa_auths must not be bundled" >&2
  exit 1
fi

ARCHIVE_NAME="grok-register-v${VERSION}-${PLATFORM}-${ARCH_LABEL}.zip"
OUT_ZIP="dist/${ARCHIVE_NAME}"
rm -f "$OUT_ZIP"
(
  cd dist
  if command -v zip >/dev/null 2>&1; then
    zip -r "$ARCHIVE_NAME" grok-register
  else
    "$PYTHON" - <<PY
import shutil
shutil.make_archive("grok-register-v${VERSION}-${PLATFORM}-${ARCH_LABEL}", "zip", root_dir=".", base_dir="grok-register")
print("[build] archived via shutil")
PY
  fi
)

if [[ ! -f "$OUT_ZIP" ]]; then
  echo "[build] ERROR: archive missing: $OUT_ZIP" >&2
  exit 1
fi
SIZE="$(wc -c < "$OUT_ZIP" | tr -d ' ')"
if [[ "$SIZE" -lt 1000000 ]]; then
  echo "[build] ERROR: archive suspiciously small (${SIZE} bytes): $OUT_ZIP" >&2
  exit 1
fi

echo "[build] OK: $OUT_ZIP (${SIZE} bytes)"

# Optional smoke: --help / --version (skip GUI)
BIN="$APP_DIR/grok-register"
if [[ -x "$BIN" ]]; then
  echo "[build] smoke: --version"
  "$BIN" --version || true
  echo "[build] smoke: --help"
  "$BIN" --help || true
fi

echo "[build] done"
