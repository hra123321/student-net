"""
管理员权限与开机自启工具
"""
import ctypes
import logging
import os
import subprocess
import sys
import threading

logger = logging.getLogger("CampusNet.Admin")

TASK_NAME = "校园网登录助手"
CREATE_NO_WINDOW = 0x08000000


def _app_path() -> str:
    """返回当前应用 EXE/脚本路径。"""
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


def _run_hidden(args, timeout: int = 10):
    """运行系统命令，带超时和隐藏窗口，避免安装/启动卡死。"""
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        logger.warning("命令超时: %s", " ".join(args[:2]))
        return None
    except Exception as e:
        logger.warning("命令执行失败: %s", e)
        return None


def is_admin() -> bool:
    """检测当前是否以管理员权限运行。"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def elevate(timeout: int = 5) -> bool:
    """以管理员权限重启当前程序，带超时保护，避免 UAC 异常卡死。"""
    if is_admin():
        return True

    logger.info("请求管理员权限...")
    result = {"ret": 0, "done": False}

    def _do_elevate():
        try:
            script = _app_path()
            params = " ".join(sys.argv[1:])
            result["ret"] = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                sys.executable,
                f'"{script}" {params}',
                None,
                1,
            )
        except Exception as e:
            logger.error("提权失败: %s", e)
        finally:
            result["done"] = True

    worker = threading.Thread(target=_do_elevate, daemon=True)
    worker.start()
    worker.join(timeout=timeout)

    if not result["done"]:
        logger.warning("提权请求超时，继续以普通权限运行")
        return False

    if result["ret"] > 32:
        logger.info("已启动管理员进程，退出当前非管理员进程")
        sys.exit(0)

    logger.warning("提权未完成或被用户取消: %s", result["ret"])
    return False


def set_auto_start(enable: bool = True, app_name: str = TASK_NAME):
    """设置/取消开机自启：优先使用计划任务最高权限运行。"""
    task_name = app_name or TASK_NAME
    if enable:
        exe_path = _app_path()
        task_run = f'"{exe_path}" --background'
        result = _run_hidden(
            [
                "schtasks",
                "/Create",
                "/F",
                "/TN",
                task_name,
                "/TR",
                task_run,
                "/SC",
                "ONLOGON",
                "/RL",
                "HIGHEST",
            ],
            timeout=15,
        )
        if result and result.returncode == 0:
            logger.info("开机自启计划任务已启用")
            return True
        stderr = (result.stderr or result.stdout).strip() if result else "无返回"
        logger.warning("设置计划任务失败: %s", stderr)
        return False

    result = _run_hidden(["schtasks", "/Delete", "/F", "/TN", task_name], timeout=10)
    if result and result.returncode == 0:
        logger.info("开机自启计划任务已删除")
        return True
    return False


def check_auto_start(app_name: str = TASK_NAME) -> bool:
    """检查计划任务自启是否存在。"""
    task_name = app_name or TASK_NAME
    result = _run_hidden(["schtasks", "/Query", "/TN", task_name], timeout=8)
    return bool(result and result.returncode == 0)
