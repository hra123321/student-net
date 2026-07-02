"""
全局防崩溃机制
- 线程安全包装器
- 看门狗定时器
- 进程清理
- 日志轮转
"""
import functools
import gc
import logging
import os
import subprocess
import sys
import threading
import time
import traceback

from utils.paths import data_dir

logger = logging.getLogger("CampusNet.AntiCrash")

DATA_DIR = data_dir()
LOG_FILE = os.path.join(DATA_DIR, "crash.log")


def setup_logging():
    """初始化日志系统"""
    os.makedirs(DATA_DIR, exist_ok=True)

    # 文件日志（带轮转：保留 7 天）
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    # 控制台日志
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    root = logging.getLogger("CampusNet")
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)

    # 清理旧日志（7天滚动）
    _rotate_logs()


def _rotate_logs():
    """日志轮转：保留 7 天"""
    try:
        if os.path.exists(LOG_FILE):
            import datetime
            now = time.time()
            mtime = os.path.getmtime(LOG_FILE)
            if now - mtime > 86400 * 7:
                # 重命名旧日志
                old_name = LOG_FILE + "." + time.strftime("%Y%m%d", time.localtime(mtime))
                os.rename(LOG_FILE, old_name)
    except Exception:
        pass


def safe_thread(func):
    """线程安全包装器装饰器
    捕获所有异常，记录日志，自动重启
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("线程异常 [%s]: %s\n%s", func.__name__, e, tb)
            # 通知看门狗（通过全局事件）
            if hasattr(watchdog_global, "on_thread_crash"):
                watchdog_global.on_thread_crash(func.__name__)
        except SystemExit:
            pass
        except KeyboardInterrupt:
            pass
    return wrapper


# 看门狗全局引用
watchdog_global = threading.local()


class Watchdog:
    """看门狗：监控子线程存活状态"""

    def __init__(self, check_interval: int = 30):
        self._threads = {}  # name -> {thread, func, restart_count}
        self._interval = check_interval
        self._running = False
        self._lock = threading.Lock()
        self._timer = None

    def register(self, name: str, target, restart_on_crash: bool = True):
        """注册需监控的线程"""
        with self._lock:
            self._threads[name] = {
                "thread": None,
                "func": target,
                "restart_on_crash": restart_on_crash,
                "restart_count": 0,
                "alive": False,
            }

    def start_all(self):
        """启动所有注册的线程"""
        with self._lock:
            for name, info in self._threads.items():
                self._start_thread(name)

        # 启动看门狗
        self._running = True
        self._schedule_check()

    def _start_thread(self, name: str):
        """启动单个线程"""
        info = self._threads.get(name)
        if not info:
            return

        t = threading.Thread(target=info["func"], name=name, daemon=True)
        t.start()
        info["thread"] = t
        info["alive"] = True
        logger.info("线程已启动: %s", name)

    def _schedule_check(self):
        if not self._running:
            return
        self._timer = threading.Timer(self._interval, self._check_all)
        self._timer.daemon = True
        self._timer.start()

    def _check_all(self):
        """检查所有线程是否存活"""
        with self._lock:
            for name, info in self._threads.items():
                t = info["thread"]
                if t and not t.is_alive():
                    logger.warning("线程挂了: %s (已重启 %d 次)",
                                   name, info["restart_count"])
                    if info["restart_on_crash"]:
                        info["restart_count"] += 1
                        self._start_thread(name)

        self._schedule_check()

    def stop(self):
        """停止看门狗"""
        self._running = False
        if self._timer:
            self._timer.cancel()


class ProcessCleaner:
    """进程清理器"""

    @staticmethod
    def cleanup_runtime():
        """长期驻留维护：触发 GC，并在 Windows 上温和整理工作集。"""
        try:
            collected = gc.collect()
            logger.debug("GC 清理完成: %d", collected)
        except Exception as e:
            logger.debug("GC 清理失败: %s", e)

        try:
            if os.name == "nt":
                import ctypes
                handle = ctypes.windll.kernel32.GetCurrentProcess()
                ctypes.windll.psapi.EmptyWorkingSet(handle)
        except Exception as e:
            logger.debug("工作集整理失败: %s", e)

    @staticmethod
    def cleanup_edge():
        """清理可能残留的 Edge 进程"""
        logger.debug("当前版本不再调用 Edge，跳过浏览器进程清理")
        return
        try:
            # 查找由本程序启动的 Edge（通过命令行含特定标记）
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq msedge.exe", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5, creationflags=0x08000000
            )
            if "msedge.exe" in result.stdout:
                pids = []
                for line in result.stdout.strip().split("\n")[1:]:
                    parts = line.strip('"').split('","')
                    if len(parts) >= 2:
                        pid = parts[1].strip('"')
                        if pid.isdigit():
                            pids.append(pid)

                if len(pids) > 3:  # 超过合理数量
                    logger.warning("检测到过多 Edge 进程 (%d 个)，执行清理", len(pids))
                    # 先温和关闭
                    for pid in pids[:-2]:  # 保留最少进程
                        subprocess.run(
                            ["taskkill", "/PID", pid, "/T"],
                            capture_output=True, timeout=3, creationflags=0x08000000
                        )
        except Exception as e:
            logger.debug("Edge 进程清理: %s", e)
