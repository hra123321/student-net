# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 构建配置
生成单目录 EXE，嵌入管理员 UAC 清单
"""
import os
import sys

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("config.example.json", "."),
    ],
    hiddenimports=[
        "email",
        "ctypes",
        "ctypes.wintypes",
        "json",
        "logging",
        "hashlib",
        "hmac",
        "struct",
        "socket",
        "threading",
        "time",
        "uuid",
        "urllib.request",
        "urllib.parse",
        "urllib.error",
        "re",
        "platform",
        "subprocess",
        "psutil",
        "win32api",
        "win32gui",
        "win32con",
        "pywintypes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter.test",
        "unittest",
        "pydoc",
        
        "http.server",
        "xmlrpc",
        "distutils",
        "lib2to3",
        "multiprocessing",
    ],
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
    name="校园网登录助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,  # 请求管理员权限
    icon=None,
)
