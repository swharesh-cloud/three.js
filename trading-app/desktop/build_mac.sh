#!/usr/bin/env bash
# Builds "Liquid Strategy Trader.app" and a .dmg. Run on a Mac from the trading-app folder:
#   bash desktop/build_mac.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .build-venv
source .build-venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt -r desktop/requirements-desktop.txt

rm -rf build dist
python desktop/make_icon.py build/icon.png
mkdir -p build/icon.iconset
for s in 16 32 128 256 512; do
  sips -z $s $s build/icon.png --out build/icon.iconset/icon_${s}x${s}.png >/dev/null
  sips -z $((s*2)) $((s*2)) build/icon.png --out build/icon.iconset/icon_${s}x${s}@2x.png >/dev/null
done
iconutil -c icns build/icon.iconset -o build/icon.icns

pyinstaller desktop/liquid_trader.spec --noconfirm

APP="dist/Liquid Strategy Trader.app"
# Ad-hoc signature so macOS will launch it (not notarized: first open needs right-click > Open).
codesign --force --deep --sign - "$APP"

mkdir -p dist/dmg
cp -R "$APP" dist/dmg/
ln -s /Applications dist/dmg/Applications
hdiutil create -volname "Liquid Strategy Trader" -srcfolder dist/dmg -ov -format UDZO "dist/Liquid-Strategy-Trader-$(uname -m).dmg"
echo "Built: dist/Liquid-Strategy-Trader-$(uname -m).dmg"
