import os

base = r"C:\Users\123\Documents\校园网登录助手"

# === Fix 1: tray.py - add WNDCLASSW structure ===
path = os.path.join(base, "ui", "tray.py")
content = open(path, "r", encoding="utf-8").read()

# After the GUID class definition, add WNDCLASSW
old_guid = '''class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_byte * 8),
    ]'''

new_guid = '''class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_byte * 8),
    ]


# WNDCLASSW - Python 3.12+ 的 ctypes.wintypes 已移除该结构
class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
    ]'''

content = content.replace(old_guid, new_guid)

# Also fix the _register_window_class method to use our WNDCLASSW
old_wc = '''        wnd_class = ctypes.wintypes.WNDCLASSW()'''
new_wc = '''        wnd_class = WNDCLASSW()'''
content = content.replace(old_wc, new_wc)

open(path, "w", encoding="utf-8").write(content)
print("tray.py: fixed WNDCLASSW")

# === Fix 2: main.py - _load_config use utf-8-sig ===
path2 = os.path.join(base, "main.py")
content2 = open(path2, "r", encoding="utf-8").read()

old_load = '''            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)'''
new_load = '''            with open(path, "r", encoding="utf-8-sig") as f:
                loaded = json.load(f)'''
content2 = content2.replace(old_load, new_load)

# Also fix config.example.json copy - need to strip BOM from copied file
old_copy = '''            import shutil
            shutil.copy(example_path, config_path)
            logger.info("已从 config.example.json 复制配置")'''
new_copy = '''            import shutil, codecs
            # 读取模板（可能带 BOM）并写入无 BOM 副本
            with codecs.open(example_path, "r", encoding="utf-8-sig") as fr:
                raw = fr.read()
            with open(config_path, "w", encoding="utf-8") as fw:
                fw.write(raw)
            logger.info("已从 config.example.json 复制配置（已去除 BOM）")'''
content2 = content2.replace(old_copy, new_copy)

open(path2, "w", encoding="utf-8").write(content2)
print("main.py: fixed UTF-8 BOM handling")

# === Fix 3: config.example.json - regenerate without BOM ===
import json
cfg = {
    "portal_url": "http://192.168.151.10",
    "login_page": "/srun_portal_pc",
    "username": "你的学号",
    "password": "你的密码",
    "ac_id": "1",
    "check_interval": 30,
    "retry_max": 5,
    "retry_cooldown": 180,
    "auto_start": True,
    "keepalive_ping_interval": 30,
    "keepalive_http_interval": 120
}
with open(os.path.join(base, "config.example.json"), "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
print("config.example.json: regenerated without BOM")

# === Fix 4: version.py ===
with open(os.path.join(base, "version.py"), "w", encoding="utf-8") as f:
    f.write("VERSION = '1.4'\nBUILD_DATE = '2026-06-08'\n")
# Fix setup.iss
iss = open(os.path.join(base, "installer", "setup.iss"), "r", encoding="utf-8").read()
iss = iss.replace('"1.3"', '"1.4"')
open(os.path.join(base, "installer", "setup.iss"), "w", encoding="utf-8").write(iss)
print("versions updated to 1.4")

print("\nALL FIXES DONE")
