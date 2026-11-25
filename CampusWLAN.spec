# -*- mode: python ; coding: utf-8 -*-

a = Analysis(["desktop_app.py"], pathex=[], binaries=[], datas=[], hiddenimports=[])
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CampusWLAN",
    console=False,
    upx=False,
)
