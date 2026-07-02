"""运行路径工具：源码、安装版、便携版统一使用可写用户数据目录。"""
import os
import sys


APP_NAME = "校园网登录助手"


def app_base_dir() -> str:
    """返回程序文件所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundled_dir() -> str:
    """返回 PyInstaller 临时资源目录或源码目录。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", app_base_dir())
    return app_base_dir()


def user_data_dir() -> str:
    """返回普通用户也一定可写的数据目录。"""
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    path = os.path.join(root, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def data_dir() -> str:
    path = os.path.join(user_data_dir(), "data")
    os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    return os.path.join(user_data_dir(), "config.json")
