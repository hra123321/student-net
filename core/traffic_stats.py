"""
流量统计模块
- 本次开机流量（基于进程启动时的基准差值）
- 自然日累计流量（JSON 持久化，重启不丢）
"""
import json
import logging
import os
import sys
import time
import psutil
from typing import Dict

logger = logging.getLogger("CampusNet.Traffic")

# PyInstaller compat
if getattr(sys, "frozen", False):
    DATA_DIR = os.path.join(os.path.dirname(sys.executable), "data")
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
TRAFFIC_FILE = os.path.join(DATA_DIR, "traffic_daily.json")


class TrafficStats:
    """流量统计器"""

    def __init__(self):
        # 本次开机流量基准值（程序启动时的计数）
        self._baseline = self._get_current_counters()
        self._last_counters = self._baseline
        # 本次开机流量
        self.session_sent = 0
        self.session_recv = 0
        self.session_total = 0
        # 历史速率
        self._last_time = time.time()
        self._last_speed_sent = 0
        self._last_speed_recv = 0
        # 当日流量（带持久化）
        self.daily = self._load_daily()
        self._today = time.strftime("%Y-%m-%d")
        self._ensure_today()

    @staticmethod
    def _get_current_counters() -> Dict:
        """获取当前所有网卡的总流量计数"""
        counters = psutil.net_io_counters(pernic=False)
        return {
            "bytes_sent": counters.bytes_sent,
            "bytes_recv": counters.bytes_recv,
            "time": time.time()
        }

    def _load_daily(self) -> Dict:
        """从 JSON 文件加载自然日流量"""
        try:
            if os.path.exists(TRAFFIC_FILE):
                with open(TRAFFIC_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning("读取日流量文件失败: %s", e)
        return {}

    def _save_daily(self):
        """保存自然日流量到 JSON 文件"""
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(TRAFFIC_FILE, "w", encoding="utf-8") as f:
                json.dump(self.daily, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存日流量文件失败: %s", e)

    def _ensure_today(self):
        """确保今日流量有记录"""
        if self._today not in self.daily:
            self.daily[self._today] = {"sent": 0, "recv": 0}
            self._save_daily()

    def update(self):
        """更新流量数据（每秒调用）"""
        current = self._get_current_counters()
        now = current["time"]

        # 计算本次开机流量
        self.session_sent = max(0, current["bytes_sent"] - self._baseline["bytes_sent"])
        self.session_recv = max(0, current["bytes_recv"] - self._baseline["bytes_recv"])
        self.session_total = self.session_sent + self.session_recv

        # 计算速率 (bytes/s)
        elapsed = now - self._last_time
        if elapsed > 0:
            self._last_speed_sent = max(0, (current["bytes_sent"] - self._last_counters["bytes_sent"])) / elapsed
            self._last_speed_recv = max(0, (current["bytes_recv"] - self._last_counters["bytes_recv"])) / elapsed
        else:
            self._last_speed_sent = 0
            self._last_speed_recv = 0

        self._last_counters = current
        self._last_time = now

        # 更新自然日流量（使用差值）
        self._ensure_today()
        self.daily[self._today]["sent"] += self._last_speed_sent * elapsed
        self.daily[self._today]["recv"] += self._last_speed_recv * elapsed
        # 每天保存一次（或在 update 中不频繁保存）
        if int(now) % 60 == 0:  # 每分钟左右保存一次
            self._save_daily()

    def get_session_stats(self) -> Dict:
        return {
            "sent": self.session_sent,
            "recv": self.session_recv,
            "total": self.session_total,
            "speed_sent": self._last_speed_sent,
            "speed_recv": self._last_speed_recv,
        }

    def get_daily_stats(self) -> Dict:
        self._ensure_today()
        return self.daily[self._today]

    @staticmethod
    def format_bytes(b: float) -> str:
        """格式化字节数为可读字符串"""
        if b < 1024:
            return f"{b:.0f} B"
        elif b < 1024 * 1024:
            return f"{b / 1024:.1f} KB"
        elif b < 1024 * 1024 * 1024:
            return f"{b / 1024 / 1024:.1f} MB"
        else:
            return f"{b / 1024 / 1024 / 1024:.2f} GB"

    @staticmethod
    def format_speed(bps: float) -> str:
        """格式化速率 bytes/s 为可读字符串"""
        return TrafficStats.format_bytes(bps) + "/s"
