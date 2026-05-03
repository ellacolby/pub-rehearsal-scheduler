#!/usr/bin/env bash
# Build a single-file executable of the PUB scheduler for the current OS/arch.
# Run from the project root with the venv activated, or this script will
# create one and install requirements.

set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "Creating .venv…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
pip install --quiet pyinstaller

rm -rf build dist pub-scheduler.spec

pyinstaller \
  --onefile \
  --name pub-scheduler \
  --collect-all ortools \
  --collect-submodules google \
  --collect-submodules googleapiclient \
  run.py

# Drop a launcher next to the binary so end-users can double-click it.
case "$(uname)" in
  Darwin)
    cat > dist/Run\ PUB\ Scheduler.command <<'LAUNCHER'
#!/usr/bin/env bash
cd "$(dirname "$0")"
./pub-scheduler
LAUNCHER
    chmod +x "dist/Run PUB Scheduler.command"
    echo
    echo "Built: dist/pub-scheduler  +  dist/Run PUB Scheduler.command"
    echo "On first launch, right-click the .command file → Open (to bypass macOS quarantine)."
    ;;
  Linux)
    echo "Built: dist/pub-scheduler"
    ;;
  *)
    echo "Built: dist/pub-scheduler"
    ;;
esac

# Package the distribution: copy config + credentials into dist/, rename
# folder to "PUB Scheduler", and zip it for easy sharing.
echo
echo "Packaging…"

PKG_DIR="dist/PUB Scheduler"
rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR"
mv dist/pub-scheduler "$PKG_DIR/"
[ -f "dist/Run PUB Scheduler.command" ] && mv "dist/Run PUB Scheduler.command" "$PKG_DIR/"

if [[ -f config.toml ]]; then
  cp config.toml "$PKG_DIR/"
else
  echo "  ⚠️  config.toml not found in project root — skipping (you'll need to add one before distributing)."
fi

if [[ -f credentials.json ]]; then
  cp credentials.json "$PKG_DIR/"
else
  echo "  ⚠️  credentials.json not found in project root — skipping (you'll need to add one before distributing)."
fi

# Include the README so end-users have offline reference for everything,
# including how to fill out the conflict sheet.
if [[ -f README.md ]]; then
  cp README.md "$PKG_DIR/Instructions.md"
fi

# Zip it from inside dist/ so the archive contains the "PUB Scheduler" folder at root.
(cd dist && rm -f "PUB Scheduler.zip" && zip -qr "PUB Scheduler.zip" "PUB Scheduler")

echo
echo "✅ Ready to share: dist/PUB Scheduler.zip"
echo
echo "Send that zip to your teammates (Google Drive, iMessage, etc.). They just"
echo "unzip it, then right-click 'Run PUB Scheduler.command' → Open."
