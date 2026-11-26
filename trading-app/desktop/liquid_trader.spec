# PyInstaller spec for the desktop app. Build with desktop/build_mac.sh on macOS.
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "build", "icon.icns")

a = Analysis(
    [os.path.join(ROOT, "desktop", "launcher.py")],
    pathex=[ROOT],
    datas=[
        (os.path.join(ROOT, "static"), "static"),
        (os.path.join(ROOT, "user_strategies"), "user_strategies"),
        (os.path.join(ROOT, ".env.example"), "."),
        (os.path.join(ROOT, "liquid_endpoints.example.json"), "."),
    ],
    hiddenimports=collect_submodules("app") + collect_submodules("uvicorn"),
    excludes=["pytest", "tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Liquid Strategy Trader",
          console=False, argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Liquid Strategy Trader")
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Liquid Strategy Trader.app",
        icon=ICON if os.path.exists(ICON) else None,
        bundle_identifier="app.liquidstrategytrader.desktop",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
