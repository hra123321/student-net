"""
管理员权限与开机自启工具
"""
import ctypes
import logging
import os
import subprocess
import sys
import winreg

logger = logging.getLogger("CampusNet.Admin")


def is_admin() -> bool:
    """检测当前是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def elevate():
    """以管理员权限重新启动当前程序"""
    if is_admin():
        return True

    logger.info("请求管理员权限...")
    script = sys.argv[0]
    params = " ".join(sys.argv[1:])

    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}" {params}', None, 1
        )
    except Exception as e:
        logger.error("提权失败: %s", e)
        return False

    # 退出当前非管理员进程
    sys.exit(0)


def set_auto_start(enable: bool = True, app_name: str = "校园网登录助手"):
    """设置/取消开机自启（HKCU 当前用户）"""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    exe_path = sys.argv[0]

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}"')
            logger.info("开机自启已启用")
        else:
            try:
                winreg.DeleteValue(key, app_name)
                logger.info("开机自启已禁用")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        logger.error("设置开机自启失败: %s", e)
        return False


def check_auto_start(app_name: str = "校园网登录助手") -> bool:
    """检查是否已启用开机自启"""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, app_name)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False
