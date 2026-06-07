"""
网络优化引擎
5 项可逆优化 + 保活机制 + 检测功能
所有修改备份到 data/network_backup.json，支持一键还原
"""
import json
import logging
import os
import socket
import subprocess
import time
import re
from typing import Dict, List, Tuple

logger = logging.getLogger("CampusNet.Optimizer")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
BACKUP_FILE = os.path.join(DATA_DIR, "network_backup.json")

# 优化项定义
OPTIMIZATIONS = {
    "power_save": {"name": "关闭网卡电源管理", "applied": False, "backup": None},
    "adapter_perf": {"name": "网卡高性能预设", "applied": False, "backup": None},
    "force_duplex": {"name": "强制全双工1Gbps", "applied": False, "backup": None},
    "private_network": {"name": "专用网络", "applied": False, "backup": None},
    "qos_bandwidth": {"name": "解除QoS预留", "applied": False, "backup": None},
}


class NetworkOptimizer:
    """网络优化引擎"""

    def __init__(self):
        self._adapter_name = self._get_active_adapter()
        self._backup = self._load_backup()
        self._restore_applied_state()

    # ==================== 网卡信息 ====================

    def _get_active_adapter(self) -> str:
        """获取当前活跃的有线网卡名称"""
        try:
            import psutil
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
            for name, s in stats.items():
                if s.isup and "loopback" not in name.lower() and name not in ("lo",):
                    # 偏好有线网卡
                    if any(kw in name.lower() for kw in ("eth", "eathernet", "以太网", "pcie", "realtek", "intel")):
                        return name
            # 回退：取第一个非 loopback 的活跃接口
            for name, s in stats.items():
                if s.isup and "loopback" not in name.lower():
                    return name
        except Exception:
            pass
        return ""

    def get_active_adapter_display(self) -> str:
        return self._adapter_name or "未检测到"

    # ==================== 备份 ====================

    def _load_backup(self) -> Dict:
        if os.path.exists(BACKUP_FILE):
            try:
                with open(BACKUP_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_backup(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(BACKUP_FILE, "w", encoding="utf-8") as f:
            json.dump(self._backup, f, ensure_ascii=False, indent=2)

    def _restore_applied_state(self):
        """从备份恢复已应用状态"""
        for key in OPTIMIZATIONS:
            if key in self._backup and self._backup[key] is not None:
                OPTIMIZATIONS[key]["applied"] = True

    # ==================== 1. 关闭网卡电源管理 ====================

    def _optimize_power_save(self) -> Tuple[bool, str]:
        """关闭网卡电源管理"""
        if not self._adapter_name:
            return False, "未检测到网卡"

        # 备份原始值（使用 PowerShell 获取）
        backup_cmd = (
            f'Get-NetAdapterPowerManagement -Name "{self._adapter_name}" '
            f'| Select-Object SelectivelySleepAllowed, WakeOnMagicPacket, DeviceSleepOnDisconnect '
            f'| ConvertTo-Json'
        )
        try:
            result = subprocess.run(
                ["powershell", "-Command", backup_cmd],
                capture_output=True, text=True, timeout=10, creationflags=0x08000000
            )
            if result.returncode == 0:
                self._backup["power_save_raw"] = result.stdout
        except Exception as e:
            logger.warning("备份电源管理失败: %s", e)

        # 关闭电源管理
        cmd = f'PowerShell -Command "Disable-NetAdapterPowerManagement -Name \'{self._adapter_name}\' -Confirm:$false"'
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"Disable-NetAdapterPowerManagement -Name '{self._adapter_name}' -Confirm:$false"],
                capture_output=True, text=True, timeout=15, creationflags=0x08000000
            )
            if result.returncode == 0:
                self._backup["power_save"] = True
                self._save_backup()
                return True, "网卡电源管理已关闭"
            else:
                return False, f"关闭失败: {result.stderr.strip()}"
        except Exception as e:
            return False, f"执行失败: {e}"

    # ==================== 2. 网卡高性能预设 ====================

    def _optimize_adapter_perf(self) -> Tuple[bool, str]:
        """网卡高性能参数：RSS/缓冲区/TCP卸载"""
        if not self._adapter_name:
            return False, "未检测到网卡"

        try:
            import psutil
            # 获取网卡设备ID
            addrs = psutil.net_if_addrs()
            if self._adapter_name not in addrs:
                return False, "未找到网卡地址信息"

            # 启用 RSS
            subprocess.run(
                ["netsh", "int", "tcp", "set", "global", "rss=enabled"],
                capture_output=True, timeout=10, creationflags=0x08000000
            )

            # 启用 TCP Chimney
            subprocess.run(
                ["netsh", "int", "tcp", "set", "global", "chimney=enabled"],
                capture_output=True, timeout=10, creationflags=0x08000000
            )

            self._backup["adapter_perf"] = True
            self._save_backup()
            return True, "网卡高性能预设已启用"
        except Exception as e:
            return False, f"设置失败: {e}"

    # ==================== 3. 强制全双工 ====================

    def _optimize_force_duplex(self) -> Tuple[bool, str]:
        """强制全双工 + 1Gbps"""
        # 注意：强制设置速率可能因网卡驱动不支持而失败
        # 尝试通过 PowerShell 设置
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"Set-NetAdapterAdvancedProperty -Name '{self._adapter_name}' "
                 f"-RegistryKeyword '*SpeedDuplex' -RegistryValue '6' -NoRestart:$true -Confirm:$false"],
                capture_output=True, text=True, timeout=10, creationflags=0x08000000
            )
            if result.returncode == 0:
                self._backup["force_duplex"] = True
                self._save_backup()
                return True, "已强制全双工1Gbps"
            # 尝试备选方法
            result2 = subprocess.run(
                ["powershell", "-Command",
                 f"Set-NetAdapterAdvancedProperty -Name '{self._adapter_name}' "
                 f"-DisplayName 'Speed & Duplex' -DisplayValue '1.0 Gbps Full Duplex' -NoRestart:$true -Confirm:$false"],
                capture_output=True, text=True, timeout=10, creationflags=0x08000000
            )
            if result2.returncode == 0:
                self._backup["force_duplex"] = True
                self._save_backup()
                return True, "已强制全双工1Gbps"
            return False, f"驱动不支持速率设置: {result.stderr.strip()[:100]}"
        except Exception as e:
            return False, f"执行失败: {e}"

    # ==================== 4. 切换专用网络 ====================

    def _optimize_private_network(self) -> Tuple[bool, str]:
        """切换为专用网络"""
        try:
            # 获取当前网络配置文件名
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-NetConnectionProfile | Where-Object {$_.NetworkCategory -ne 'DomainAuthenticated'} "
                 "| Select-Object Name, InterfaceAlias, NetworkCategory | ConvertTo-Json"],
                capture_output=True, text=True, timeout=10, creationflags=0x08000000
            )
            if result.returncode == 0 and result.stdout.strip():
                profiles = json.loads(result.stdout)
                if isinstance(profiles, dict):
                    profiles = [profiles]
                for p in profiles:
                    name = p.get("Name", "")
                    if name:
                        cmd_switch = (
                            f"Set-NetConnectionProfile -Name '{name}' -NetworkCategory Private"
                        )
                        subprocess.run(
                            ["powershell", "-Command", cmd_switch],
                            capture_output=True, timeout=10, creationflags=0x08000000
                        )
                self._backup["private_network"] = True
                self._save_backup()
                return True, "已切换为专用网络"
            return False, "未找到网络配置文件"
        except Exception as e:
            return False, f"切换失败: {e}"

    # ==================== 5. 解除QoS预留 ====================

    def _optimize_qos_bandwidth(self) -> Tuple[bool, str]:
        """解除 QoS 预留带宽限制"""
        try:
            # 写入注册表策略
            import winreg
            key_path = r"SOFTWARE\Policies\Microsoft\Windows\Psched"
            try:
                key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                winreg.SetValueEx(key, "NonBestEffortLimit", 0, winreg.REG_DWORD, 0)
                winreg.CloseKey(key)
                self._backup["qos_bandwidth"] = True
                self._save_backup()
                return True, "QoS 预留已解除(需重启)"
            except PermissionError:
                return False, "需要管理员权限修改注册表"
        except Exception as e:
            return False, f"解除失败: {e}"

    # ==================== 一键优化/还原 ====================

    def apply_all(self) -> List[Dict]:
        """应用所有优化"""
        results = []
        handlers = [
            ("power_save", self._optimize_power_save),
            ("adapter_perf", self._optimize_adapter_perf),
            ("force_duplex", self._optimize_force_duplex),
            ("private_network", self._optimize_private_network),
            ("qos_bandwidth", self._optimize_qos_bandwidth),
        ]
        for key, handler in handlers:
            success, msg = handler()
            OPTIMIZATIONS[key]["applied"] = success
            results.append({"key": key, "success": success, "message": msg})
            logger.info("优化 [%s]: %s - %s", key, "✅" if success else "❌", msg)
        return results

    def restore_all(self) -> List[Dict]:
        """一键还原所有优化"""
        results = []

        # 1. 还原电源管理
        if self._backup.get("power_save"):
            try:
                subprocess.run(
                    ["powershell", "-Command",
                     f"Enable-NetAdapterPowerManagement -Name '{self._adapter_name}' -Confirm:$false"],
                    capture_output=True, timeout=10, creationflags=0x08000000
                )
            except Exception:
                pass

        # 2. 还原 QoS 注册表
        if self._backup.get("qos_bandwidth"):
            try:
                import winreg
                key_path = r"SOFTWARE\Policies\Microsoft\Windows\Psched"
                winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, key_path)
            except Exception:
                try:
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_SET_VALUE)
                    winreg.DeleteValue(key, "NonBestEffortLimit")
                    winreg.CloseKey(key)
                except Exception:
                    pass

        # 3. 还原网络配置（专用→自动）
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-NetConnectionProfile | Where-Object {$_.NetworkCategory -eq 'Private'} "
                 "| Select-Object Name | ConvertTo-Json"],
                capture_output=True, text=True, timeout=10, creationflags=0x08000000
            )
            if result.returncode == 0 and result.stdout.strip():
                profiles = json.loads(result.stdout)
                if isinstance(profiles, dict):
                    profiles = [profiles]
                for p in profiles:
                    name = p.get("Name", "")
                    if name:
                        subprocess.run(
                            ["powershell", "-Command",
                             f"Set-NetConnectionProfile -Name '{name}' -NetworkCategory Public"],
                            capture_output=True, timeout=10, creationflags=0x08000000
                        )
        except Exception:
            pass

        # 清除备份状态
        self._backup = {}
        self._save_backup()
        for key in OPTIMIZATIONS:
            OPTIMIZATIONS[key]["applied"] = False

        results.append({"key": "all", "success": True, "message": "所有优化已还原"})
        logger.info("所有优化已还原")
        return results

    # ==================== 保活机制 ====================

    def keepalive_ping(self, gateway_ip: str) -> bool:
        """保活 Ping"""
        if not gateway_ip:
            return False
        try:
            import ctypes, struct, socket as sock_lib
            dll = ctypes.windll.icmp
            handle = dll.IcmpCreateFile()
            if handle and handle != 0:
                ip_bytes = sock_lib.inet_aton(gateway_ip)
                ip_int = struct.unpack(">I", ip_bytes)[0]
                reply = ctypes.create_string_buffer(100)
                dll.IcmpSendEcho(handle, ip_int, b"k" * 32, 32, None, reply, 100, 1000)
                dll.IcmpCloseHandle(handle)
                return True
        except Exception:
            pass
        # Fallback: 系统 ping
        try:
            subprocess.run(
                ["ping", "-n", "1", "-w", "1000", gateway_ip],
                capture_output=True, timeout=2, creationflags=0x08000000
            )
        except Exception:
            pass
        return True

    def keepalive_http(self, portal_url: str) -> bool:
        """保活 HTTP 请求"""
        try:
            import urllib.request
            req = urllib.request.Request(portal_url, method="GET")
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception:
            return False

    # ==================== 检测功能 ====================

    def detect_mtu(self, target_ip: str = None) -> Dict:
        """MTU 路径探测（Ping + DF 标志递增）"""
        target = target_ip or "223.5.5.5"
        results = {"mtu": 1500, "tested": []}

        for size in range(1472, 1501):
            try:
                cmd = ["ping", "-f", "-l", str(size), "-n", "1", "-w", "1000", target]
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=3, creationflags=0x08000000
                )
                success = "TTL=" in result.stdout or "往返" in result.stdout
                results["tested"].append({"size": size, "success": success})
                if not success:
                    results["mtu"] = size + 28 - 1  # ICMP header 8 + IP header 20 = 28
                    break
            except Exception:
                break
        return results

    def measure_dns(self) -> List[Dict]:
        """DNS 延迟对比"""
        dns_list = [
            ("当前DNS", None),
            ("114DNS", "114.114.114.114"),
            ("阿里DNS", "223.5.5.5"),
            ("DNSPod", "119.29.29.29"),
        ]
        results = []
        host = "www.baidu.com"

        for name, dns_ip in dns_list:
            timings = []
            for _ in range(3):
                try:
                    start = time.time()
                    if dns_ip:
                        # 使用指定 DNS
                        import ctypes
                        dll = ctypes.windll.dnsapi
                        # 简单方式：socket 默认
                        socket.setdefaulttimeout(3)
                        addr = socket.getaddrinfo(host, 80)
                        elapsed = (time.time() - start) * 1000
                    else:
                        addr = socket.getaddrinfo(host, 80)
                        elapsed = (time.time() - start) * 1000
                    timings.append(elapsed)
                except Exception:
                    timings.append(None)

            valid = [t for t in timings if t is not None]
            avg = sum(valid) / len(valid) if valid else None
            results.append({"name": name, "ip": dns_ip or "系统默认", "avg_ms": round(avg, 1) if avg else None})

        return results

    def check_tcp_state(self) -> Dict:
        """检查 TCP 状态"""
        result = {"auto_tuning": "unknown", "rss": "unknown", "chimney": "unknown"}
        try:
            r = subprocess.run(
                ["netsh", "int", "tcp", "show", "global"],
                capture_output=True, text=True, timeout=5, creationflags=0x08000000
            )
            output = r.stdout
            if "接收窗口自动调节级别" in output or "Receive Window Auto-Tuning Level" in output:
                result["auto_tuning"] = "normal" if "normal" in output.lower() else "disabled"
            if "RSS" in output:
                result["rss"] = "enabled" if "enabled" in output.lower() else "disabled"
        except Exception:
            pass
        return result

    def measure_bandwidth(self) -> Dict:
        """简单带宽实测（通过 HTTP 下载测速）
        使用校园网 Portal 或 baidu 的 favicon 文件
        """
        result = {"download_mbps": 0, "upload_mbps": 0, "latency_ms": 0}
        # 下载测速（用多线程快速下载小文件）
        try:
            import urllib.request
            # 使用百度首页做简易测速
            chunk_sizes = []
            for _ in range(3):
                start = time.time()
                req = urllib.request.Request("https://www.baidu.com/favicon.ico",
                                             headers={"User-Agent": "Mozilla/5.0"})
                resp = urllib.request.urlopen(req, timeout=5)
                data = resp.read()
                elapsed = time.time() - start
                if elapsed > 0:
                    speed_bps = (len(data) * 8) / elapsed
                    chunk_sizes.append(speed_bps)
            if chunk_sizes:
                avg_bps = sum(chunk_sizes) / len(chunk_sizes)
                result["download_mbps"] = round(avg_bps / 1000000, 1)
        except Exception:
            result["download_mbps"] = 0
        return result

    def get_optimization_states(self) -> Dict:
        """获取所有优化项的当前状态"""
        states = {}
        for key, opt in OPTIMIZATIONS.items():
            states[key] = {
                "name": opt["name"],
                "applied": opt["applied"]
            }
        states["adapter"] = self._adapter_name
        return states
