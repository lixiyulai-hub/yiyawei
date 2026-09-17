# PyInstaller readiness spec for offline review.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


block_cipher = None
PROJECT_ROOT = Path(SPECPATH).resolve().parent

hiddenimports = (
    collect_submodules("funasr")
    + collect_submodules("modelscope")
    + [
        "sounddevice",
        "soundfile",
        "yaml",
        "opencc",
        "pyautogui",
        "pyperclip",
    ]
)

datas = [
    (str(PROJECT_ROOT / "config.yaml"), "."),
    (str(PROJECT_ROOT / "config.no_paste.yaml"), "."),
    (str(PROJECT_ROOT / "requirements.txt"), "."),
    (str(PROJECT_ROOT / "src/gui/web_assets"), "src/gui/web_assets"),
    (str(PROJECT_ROOT / "src/glossary/tech_terms.json"), "src/glossary"),
]

a = Analysis(
    [str(PROJECT_ROOT / "app.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Yiyawei",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
