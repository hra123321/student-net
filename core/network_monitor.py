"""
网络状态检测模块
三重检测：ICMP Ping 网关 + DNS 解析 + 网卡接口状态
"""
import socket
import struct
import time
import ctypes
import ctypes.util
import threading
import logging
from typing import Tuple, Optional

logger = logging.getLogger("CampusNet")

# 网络状态常量
NETWORK_OK = "网络正常"
NETWORK_DISCONNECTED = "网络断开"
NETWORK_LIMITED = "网络受限"


class ICMPEcho:
    """使用 Windows IcmpSendEcho API 进行 ICMP Ping"""

    def __init__(self):
        self.dll = ctypes.windll.icmp
        self._setup()

    def _setup(self):
        try:
            self.IcmpCreateFile = self.dll.IcmpCreateFile
            self.IcmpCloseHandle = self.dll.IcmpCloseHandle
            self.IcmpSendEcho = self.dll.IcmpSendEcho
            self.IcmpCreateFile.restype = ctypes.c_void_p
            self.IcmpCloseHandle.restype = ctypes.c_int
            self.IcmpSendEcho.restype = ctypes.c_uint32
        except AttributeError as e:
            logger.warning("ICMP API 加载失败: %s", e)
            self.IcmpCreateFile = None

    def ping(self, ip: str, timeout_ms: int = 3000) -> Tuple[bool, float]:
        """Ping 指定 IP，返回 (是否成功, 延迟ms)"""
        if not self.IcmpCreateFile:
            return False, 0

        handle = self.IcmpCreateFile()
        if handle is None or handle == 0:
            return False, 0

        try:
            # 准备 IP 地址
            ip_bytes = socket.inet_aton(ip)
            ip_int = struct.unpack(">I", ip_bytes)[0]

            # 准备请求数据
            data = b"a" * 32
            reply_size = 8 + 32 + ctypes.sizeof(ctypes.c_uint32) * 4
            reply = ctypes.create_string_buffer(reply_size)

            start = time.time()
            ret = self.IcmpSendEcho(
                handle,
                ip_int,
                data,
                len(data),
                None,
                reply,
                reply_size,
                timeout_ms
            )
            elapsed = (time.time() - start) * 1000

            if ret == 0:
                return False, elapsed

            # 解析回复
            reply_data = bytearray(reply)
            status = struct.unpack_from("<I", reply_data, 4)[0]
            if status == 0:  # IP_SUCCESS
                return True, elapsed
            return False, elapsed
        finally:
            self.IcmpCloseHandle(handle)


class NetworkMonitor:
    """网络状态检测器"""

    def __init__(self):
        self.icmp = ICMPEcho()
        self._gateway_ip = None
        self._gateway_last_found = 0
        self._lock = threading.Lock()
        self._last_ping_latency = 0.0
        self._last_packet_loss = 0.0
        self._ping_history = []

    def get_gateway(self) -> Optional[str]:
        """获取默认网关 IP"""
        now = time.time()
        if self._gateway_ip and (now - self._gateway_last_found) < 300:
            return self._gateway_ip

        try:
            # 通过路由表获取默认网关
            import subprocess
            result = subprocess.run(
                ["route", "print", "0.0.0.0"],
                capture_output=True, text=True, creationflags=0x08000000
            )
            for line in result.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                    self._gateway_ip = parts[2]
                    self._gateway_last_found = now
                    return self._gateway_ip
        except Exception as e:
            logger.warning("获取网关失败: %s", e)
        return None

    def check_network(self) -> Tuple[str, float, float]:
        """三重检测网络状态
        返回: (状态, Ping延迟ms, 丢包率%)
        """
        status = NETWORK_DISCONNECTED
        latency = 0.0
        loss = 100.0

        # 1. 检查网卡接口状态
        try:
            import psutil
            stats = psutil.net_if_stats()
            interfaces = psutil.net_if_addrs()

            active = False
            for name, s in stats.items():
                if s.isup and name not in ("lo", "Loopback"):
                    # 检查是否有有效 IP
                    if name in interfaces:
                        for addr in interfaces[name]:
                            if addr.family == socket.AF_INET:
                                active = True
                                break
                    if active:
                        break

            if not active:
                return NETWORK_DISCONNECTED, 0, 100
        except ImportError:
            pass

        # 2. 获取网关并 Ping
        gateway = self.get_gateway()
        if gateway:
            ok, lat = self.icmp.ping(gateway, 3000)
            if ok:
                status = NETWORK_OK
                latency = lat
                # 计算丢包率（滚动记录）
                self._ping_history.append(ok)
                if len(self._ping_history) > 10:
                    self._ping_history.pop(0)
                loss_count = self._ping_history.count(False)
                loss = (loss_count / len(self._ping_history)) * 100
            else:
                status = NETWORK_LIMITED
                loss = 100
        else:
            status = NETWORK_LIMITED

        # 3. DNS 补充检测
        if status != NETWORK_OK:
            try:
                socket.gethostbyname("baidu.com")
                # DNS 通但 Ping 不通 -> 受限
                if status == NETWORK_DISCONNECTED:
                    status = NETWORK_LIMITED
            except Exception:
                if status != NETWORK_DISCONNECTED:
                    status = NETWORK_DISCONNECTED

        return status, latency, loss

    def get_ping_stats(self) -> Tuple[float, float]:
        """获取当前 Ping 延迟和丢包率"""
        return self._last_ping_latency, self._last_packet_loss
