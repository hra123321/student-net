"""
主机系统信息采集模块
"""
import platform
import socket
import time
import psutil
import logging
from typing import Dict

logger = logging.getLogger("CampusNet.SysInfo")


class SystemInfo:
    """采集主机系统信息"""

    @staticmethod
    def get_static_info() -> Dict:
        """获取不变的静态系统信息"""
        info = {
            "computer_name": platform.node(),
            "user_name": __import__("os").environ.get("USERNAME", ""),
            "os_version": platform.platform(),
        }
        return info

    @staticmethod
    def get_dynamic_info() -> Dict:
        """获取动态系统信息"""
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time

        cpu_percent = psutil.cpu_percent(interval=0)
        mem = psutil.virtual_memory()

        return {
            "uptime_seconds": uptime_seconds,
            "uptime_str": SystemInfo._format_uptime(uptime_seconds),
            "cpu_percent": cpu_percent,
            "mem_total": mem.total,
            "mem_used": mem.used,
            "mem_available": mem.available,
            "mem_percent": mem.percent,
        }

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        mins = int((seconds % 3600) // 60)
        if days > 0:
            return f"{days}天{hours}时{mins}分"
        return f"{hours}时{mins}分"
