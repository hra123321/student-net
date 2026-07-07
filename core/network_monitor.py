"""
网络状态检测模块
三重检测：ICMP Ping 网关 + DNS 解析 + 网卡接口状态
"""
import socket
import struct
import subprocess
import time
import ctypes
import ctypes.util
import logging
import re
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

            # 64位系统上句柄是64位的
            self.IcmpCreateFile.restype = ctypes.c_void_p
            self.IcmpCreateFile.argtypes = []
            self.IcmpCloseHandle.restype = ctypes.c_int
            self.IcmpCloseHandle.argtypes = [ctypes.c_void_p]
            self.IcmpSendEcho.restype = ctypes.c_uint32
            self.IcmpSendEcho.argtypes = [
                ctypes.c_void_p,       # IcmpHandle
                ctypes.c_uint32,       # DestinationAddress
                ctypes.c_void_p,       # RequestData
                ctypes.c_uint16,       # RequestSize
                ctypes.c_void_p,       # RequestOptions
                ctypes.c_void_p,       # ReplyBuffer
                ctypes.c_uint32,       # ReplySize
                ctypes.c_uint32        # Timeout
            ]
        except AttributeError as e:
            logger.warning("ICMP API 加载失败: %s", e)
            self.IcmpCreateFile = None

    def ping(self, ip: str, timeout_ms: int = 3000) -> Tuple[bool, float]:
        """Ping 指定 IP，返回 (是否成功, 延迟ms)"""
        if not self.IcmpCreateFile:
            return self._system_ping(ip, timeout_ms)

        handle = self.IcmpCreateFile()
        if not handle or handle == 0:
            return self._system_ping(ip, timeout_ms)

        try:
            ip_bytes = socket.inet_aton(ip)
            ip_int = struct.unpack("<I", ip_bytes)[0]

            # 准备请求数据
            data = (b"a" * 32)
            data_buf = ctypes.create_string_buffer(data, 32)

            # 回复缓冲区 (IP header 8 + ICMP header 8 + 32 data + 4*3 padding)
            reply_size = 64
            reply = ctypes.create_string_buffer(reply_size)

            start = time.time()
            ret = self.IcmpSendEcho(
                handle,
                ip_int,
                data_buf,
                32,
                None,
                reply,
                reply_size,
                timeout_ms
            )
            elapsed = (time.time() - start) * 1000

            success = ret > 0
            if not success:
                return self._system_ping(ip, timeout_ms)
            return success, elapsed

        except Exception as e:
            logger.debug("Ping 异常: %s", e)
            return self._system_ping(ip, timeout_ms)
        finally:
            self.IcmpCloseHandle(handle)

    @staticmethod
    def _system_ping(ip: str, timeout_ms: int = 1000) -> Tuple[bool, float]:
        """系统 ping 兜底，兼容部分机器 IcmpSendEcho 返回异常的情况。"""
        try:
            result = subprocess.run(
                ["ping", "-n", "1", "-w", str(timeout_ms), ip],
                capture_output=True, text=True, timeout=max(2, timeout_ms / 1000 + 1),
                creationflags=0x08000000
            )
            output = result.stdout
            ok = result.returncode == 0 and (
                "TTL=" in output.upper() or "ttl=" in output.lower() or "字节=" in output
            )
            if not ok:
                return False, 0
            match = re.search(r"time[=<]([0-9]+)ms", output, re.IGNORECASE)
            if not match:
                match = re.search(r"时间[=<]([0-9]+)ms", output, re.IGNORECASE)
            latency = float(match.group(1)) if match else 1.0
            return True, latency
        except Exception as e:
            logger.debug("系统 Ping 异常: %s", e)
            return False, 0


class NetworkMonitor:
    """网络状态检测器"""

    def __init__(self):
        self.icmp = ICMPEcho()
        self._gateway_ip = None
        self._gateway_last_found = 0
        self._active_interface = {}
        self._active_interface_last_found = 0
        self._ping_history = []

    @staticmethod
    def _is_virtual_adapter(name: str) -> bool:
        lowered = (name or "").lower()
        keywords = (
            "vpn", "virtual", "vmware", "hyper-v", "vethernet", "loopback",
            "bluetooth", "tap", "tunnel", "miniport", "redmi", "zerotier",
            "tailscale", "wireguard", "wintun"
        )
        return any(keyword in lowered for keyword in keywords)

    @staticmethod
    def _is_wired_adapter(name: str) -> bool:
        lowered = (name or "").lower()
        keywords = (
            "以太网", "ethernet", "realtek", "瑞昱", "pcie", "gbe",
            "2.5gbe", "intel", "killer", "lan"
        )
        return any(keyword in lowered for keyword in keywords)

    def get_active_interface(self) -> dict:
        """获取当前默认路由对应的物理网卡，优先排除 VPN/虚拟网卡。"""
        now = time.time()
        if self._active_interface and (now - self._active_interface_last_found) < 30:
            return self._active_interface

        try:
            import psutil
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
            interfaces = {}
            for name, nic_addrs in addrs.items():
                if name not in stats or not stats[name].isup:
                    continue
                info = {
                    "adapter": name,
                    "ipv4": "",
                    "mask": "",
                    "mac": "--",
                    "gateway": "",
                    "speed": stats[name].speed,
                    "media_type": "无线",
                    "virtual": self._is_virtual_adapter(name),
                    "wired": self._is_wired_adapter(name),
                }
                for addr in nic_addrs:
                    if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                        info["ipv4"] = addr.address
                        info["mask"] = addr.netmask or "--"
                    elif addr.family in (getattr(socket, "AF_LINK", object()), -1):
                        info["mac"] = addr.address
                if info["ipv4"]:
                    info["media_type"] = "有线" if info["wired"] or stats[name].speed > 100 else "无线"
                    interfaces[info["ipv4"]] = info

            candidates = []
            result = subprocess.run(
                ["route", "print", "0.0.0.0"],
                capture_output=True, text=True, timeout=5, creationflags=0x08000000
            )
            for line in result.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                    gateway = parts[2]
                    iface_ip = parts[3]
                    if iface_ip not in interfaces:
                        continue
                    try:
                        socket.inet_aton(gateway)
                    except OSError:
                        continue
                    info = dict(interfaces[iface_ip])
                    info["gateway"] = gateway
                    try:
                        metric = int(parts[4])
                    except ValueError:
                        metric = 9999
                    score = metric
                    if info["virtual"]:
                        score += 10000
                    if info["wired"]:
                        score -= 500
                    if info["speed"] and info["speed"] >= 1000:
                        score -= 100
                    candidates.append((score, info))

            if candidates:
                candidates.sort(key=lambda item: item[0])
                self._active_interface = candidates[0][1]
            else:
                fallback = sorted(
                    interfaces.values(),
                    key=lambda info: (
                        1 if info["virtual"] else 0,
                        0 if info["wired"] else 1,
                        -(info["speed"] or 0),
                    )
                )
                self._active_interface = fallback[0] if fallback else {}

            self._gateway_ip = self._active_interface.get("gateway") or None
            self._gateway_last_found = now
            self._active_interface_last_found = now
            return self._active_interface
        except Exception as e:
            logger.warning("获取活跃网卡失败: %s", e)
            return self._active_interface or {}

    def get_gateway(self) -> Optional[str]:
        """获取默认网关 IP"""
        now = time.time()
        if self._gateway_ip and (now - self._gateway_last_found) < 300:
            return self._gateway_ip

        active = self.get_active_interface()
        if active.get("gateway"):
            return active["gateway"]

        try:
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
                if s.isup and "loopback" not in name.lower() and name not in ("lo",):
                    if name in interfaces:
                        for addr in interfaces[name]:
                            if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                                active = True
                                break
                    if active:
                        break
            if not active:
                return NETWORK_DISCONNECTED, 0, 100
        except ImportError:
            pass

        # 2. Ping 网关
        gateway = self.get_gateway()
        if gateway:
            ok, lat = self.icmp.ping(gateway, 3000)
            self._ping_history.append(ok)
            if len(self._ping_history) > 10:
                self._ping_history.pop(0)
            loss_count = self._ping_history.count(False)
            loss_pct = (loss_count / max(len(self._ping_history), 1)) * 100

            if ok:
                status = NETWORK_OK
                latency = lat
                loss = loss_pct
            else:
                status = NETWORK_LIMITED
                loss = 100
        else:
            status = NETWORK_LIMITED

        # 3. DNS 补充检测
        if status != NETWORK_OK:
            try:
                socket.gethostbyname("baidu.com")
                if status == NETWORK_DISCONNECTED:
                    status = NETWORK_LIMITED
            except Exception:
                if status != NETWORK_DISCONNECTED:
                    status = NETWORK_DISCONNECTED

        return status, latency, loss
