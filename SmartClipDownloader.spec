# PyInstaller spec: builds a single-folder desktop app.
#   pip install pyinstaller
#   pyinstaller SmartClipDownloader.spec
# Output: dist/SmartClipDownloader/  (ffmpeg is not bundled; install it separately)
from pathlib import Path

ICONS = Path("smart_clip_downloader/assets/icons")

a = Analysis(
    ["SmartClipDownloader.pyw"],
    pathex=["."],
    datas=[(str(ICONS), "smart_clip_downloader/assets/icons")],
    hiddenimports=["PyQt5.QtSvg", "yt_dlp.compat._legacy", "yt_dlp.compat._deprecated"],
    excludes=["tkinter", "matplotlib", "numpy", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SmartClipDownloader",
    console=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SmartClipDownloader")
