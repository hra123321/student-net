"""
校园网登录助手 - 主入口
单例检测 → 管理员提权 → 加载配置 → 启动各线程 → 托盘驻留
"""
import ctypes
import json
import logging
import os
import sys
import threading
import time
import uuid

# 将项目根目录加入路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core.anti_crash import setup_logging, safe_thread, Watchdog, ProcessCleaner
from core.network_monitor import NetworkMonitor, NETWORK_OK, NETWORK_DISCONNECTED
from core.srun_login import SrunLogin
from core.network_optimizer import NetworkOptimizer
from core.system_info import SystemInfo
from core.traffic_stats import TrafficStats
from ui.tray import SysTrayIcon
from ui.monitor_panel import MonitorPanel
from utils.admin import is_admin, elevate, set_auto_start, check_auto_start

logger = logging.getLogger("CampusNet.Main")


class CampusNetApp:
    """主应用类：协调所有模块"""

    def __init__(self, config_path: str = None):
        # 加载配置
        if config_path is None:
            config_path = os.path.join(BASE_DIR, "config.json")
        self.config = self._load_config(config_path)

        # 初始化各模块
        self.net_monitor = NetworkMonitor()
        self.srun_login = SrunLogin(self.config)
        self.optimizer = NetworkOptimizer()
        self.sys_info = SystemInfo()
        self.traffic = TrafficStats()

        # 登录状态
        self.login_status = "等待中"       # 登录中/登录成功/登录失败/等待重试
        self.login_retry_count = 0
        self.login_retry_left = self.config.get("retry_max", 5)
        self.login_next_retry = ""
        self._login_lock = threading.Lock()
        self._last_login_attempt = 0
        self._in_cooldown = False
        self._cooldown_until = 0

        # 系统静态信息
        self._sys_static = SystemInfo.get_static_info()

        # 网络信息缓存
        self._net_info = {}
        self._speed_info = {}
        self._opt_info = {}

        # UI
        self.tray = SysTrayIcon("校园网登录助手")
        self.panel = MonitorPanel(self)

        # 看门狗
        self.watchdog = Watchdog(check_interval=30)

        # 运行标志
        self._running = False

    @staticmethod
    def _load_config(path: str) -> dict:
        """加载配置文件"""
        default_config = {
            "portal_url": "http://192.168.151.10",
            "login_page": "/srun_portal_pc",
            "username": "",
            "password": "",
            "ac_id": "1",
            "check_interval": 30,
            "retry_max": 5,
            "retry_cooldown": 180,
            "auto_start": True,
            "keepalive_ping_interval": 30,
            "keepalive_http_interval": 120,
        }
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                default_config.update(loaded)
            except Exception as e:
                logger.error("加载配置失败: %s", e)
        return default_config

    # ============ 数据提供者（供 UI 调用） ============

    def get_network_info(self) -> dict:
        """提供给 UI 的网络基础信息"""
        try:
            import psutil, socket
            import subprocess

            # 获取主网卡
            gateways = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            gateway_ip = self.net_monitor.get_gateway()

            adapter_name = ""
            mac = "--"
            ipv4 = "--"
            mask = "--"
            dns = "--"
            media_type = "--"

            # 找有默认网关的网卡
            for name, addrs in gateways.items():
                if name in stats and stats[name].isup:
                    has_ip = False
                    for addr in addrs:
                        if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                            adapter_name = name
                            ipv4 = addr.address
                            mask = addr.netmask
                            has_ip = True
                            break
                    if has_ip:
                        # 获取 MAC
                        for addr in addrs:
                            if addr.family == socket.AF_LINK or addr.family == -1:
                                mac = addr.address
                                break
                        # 判断有线/无线
                        if any(kw in name.lower() for kw in ("wi-fi", "wlan", "wireless", "802.11")):
                            media_type = "无线"
                        elif any(kw in name.lower() for kw in ("eth", "eathernet", "以太网", "pcie", "realtek", "intel")):
                            media_type = "有线"
                        else:
                            media_type = stats[name].speed > 0 and "有线" or "无线"
                        break

            # 获取 DNS
            try:
                dns_result = subprocess.run(
                    ["nslookup", "baidu.com"],
                    capture_output=True, text=True, timeout=5, creationflags=0x08000000
                )
                for line in dns_result.stdout.splitlines():
                    if "Address:" in line and "192.168" not in line and "#53" not in line:
                        dns = line.split("Address:")[-1].strip()
                        break
            except Exception:
                pass

            self._net_info = {
                "adapter": adapter_name or "--",
                "mac": mac,
                "ipv4": ipv4,
                "mask": mask,
                "gateway": gateway_ip or "--",
                "dns": dns,
                "media_type": media_type or "--",
            }
        except Exception as e:
            logger.debug("网络信息采集异常: %s", e)
        return self._net_info

    def get_speed_info(self) -> dict:
        """提供给 UI 的速率信息"""
        try:
            import psutil
            # 协商带宽
            stats = psutil.net_if_stats()
            adapter = self._net_info.get("adapter", "")
            link_speed = "--"
            if adapter and adapter in stats:
                speed_mbps = stats[adapter].speed
                if speed_mbps > 0:
                    link_speed = f"{speed_mbps} Mbps"

            # Ping 延迟
            gateway = self.net_monitor.get_gateway()
            latency = "--"
            loss = "--"
            if gateway:
                ok, lat = self.net_monitor.icmp.ping(gateway, 3000)
                if ok:
                    latency = f"{lat:.1f} ms"
                # 丢包率
                self.net_monitor._ping_history.append(ok)
                if len(self.net_monitor._ping_history) > 10:
                    self.net_monitor._ping_history.pop(0)
                loss_count = self.net_monitor._ping_history.count(False)
                loss_pct = (loss_count / max(len(self.net_monitor._ping_history), 1)) * 100
                loss = f"{loss_pct:.0f}%"

            # 实时速率
            session = self.traffic.get_session_stats()
            up = TrafficStats.format_speed(session.get("speed_sent", 0))
            down = TrafficStats.format_speed(session.get("speed_recv", 0))

            self._speed_info = {
                "up": up,
                "down": down,
                "link": link_speed,
                "latency": latency,
                "loss": loss,
            }
        except Exception as e:
            logger.debug("速率采集异常: %s", e)
        return self._speed_info

    def get_traffic_info(self) -> dict:
        """提供给 UI 的流量信息"""
        try:
            session = self.traffic.get_session_stats()
            daily = self.traffic.get_daily_stats()
            return {
                "session_up": TrafficStats.format_bytes(session.get("sent", 0)),
                "session_down": TrafficStats.format_bytes(session.get("recv", 0)),
                "session_total": TrafficStats.format_bytes(session.get("total", 0)),
                "daily_up": TrafficStats.format_bytes(daily.get("sent", 0)),
                "daily_down": TrafficStats.format_bytes(daily.get("recv", 0)),
                "daily_total": TrafficStats.format_bytes(daily.get("sent", 0) + daily.get("recv", 0)),
            }
        except Exception:
            return {}

    def get_system_info(self) -> dict:
        """提供给 UI 的系统信息"""
        dyn = self.sys_info.get_dynamic_info()
        return {
            "computer_name": self._sys_static.get("computer_name", "--"),
            "user_name": self._sys_static.get("user_name", "--"),
            "os_version": self._sys_static.get("os_version", "--"),
            "uptime": dyn.get("uptime_str", "--"),
            "cpu_percent": dyn.get("cpu_percent", 0),
            "mem_percent": dyn.get("mem_percent", 0),
            "mem_used": dyn.get("mem_used", 0),
            "mem_total": dyn.get("mem_total", 0),
        }

    def get_login_info(self) -> dict:
        """提供给 UI 的登录状态"""
        # 网络状态
        net_status = NETWORK_DISCONNECTED
        gateway = self.net_monitor.get_gateway()
        if gateway:
            ok, _ = self.net_monitor.icmp.ping(gateway, 2000)
            if ok:
                net_status = NETWORK_OK
            else:
                net_status = "网络受限"

        # 倒计时
        next_retry = self.login_next_retry
        if self._cooldown_until and time.time() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.time())
            next_retry = f"{remaining // 60}分{remaining % 60}秒后"

        return {
            "net_status": net_status,
            "login_status": self.login_status,
            "retry_left": str(self.login_retry_left),
            "next_retry": next_retry,
            "edge_status": "未使用",
        }

    def get_optimize_info(self) -> dict:
        """提供给 UI 的优化信息"""
        try:
            states = self.optimizer.get_optimization_states()

            # DNS 检测
            dns_result = self.optimizer.measure_dns()
            dns_best = "--"
            for d in dns_result:
                if d.get("avg_ms") is not None:
                    dns_best = f"{d['name']} ({d['avg_ms']}ms)"
                    break

            # MTU 检测
            mtu_result = self.optimizer.detect_mtu()
            mtu_str = f"{mtu_result.get('mtu', 1500)}"

            # 带宽
            bw = self.optimizer.measure_bandwidth()
            bw_str = f"{bw.get('download_mbps', 0)} Mbps"

            # TCP
            tcp = self.optimizer.check_tcp_state()
            tcp_str = "正常" if tcp.get("auto_tuning") == "normal" else "需优化"

            # 电源管理
            ps = states.get("power_save", {})
            ps_str = "✅ 已关闭" if ps.get("applied") else "⚠️ 建议关闭"

            # 网络配置
            pn = states.get("private_network", {})
            pn_str = "✅ 专用网络" if pn.get("applied") else "⚠️ 建议切换"

            self._opt_info = {
                "bandwidth": bw_str,
                "mtu": mtu_str,
                "dns_best": dns_best,
                "power_save": ps_str,
                "tcp_state": tcp_str,
                "net_profile": pn_str,
            }
        except Exception as e:
            logger.debug("优化信息采集异常: %s", e)
        return self._opt_info

    # ============ 核心功能线程 ============

    @safe_thread
    def _login_worker(self):
        """登录工作线程：自动检测并执行登录"""
        max_retry = self.config.get("retry_max", 5)
        cooldown = self.config.get("retry_cooldown", 180)
        check_interval = self.config.get("check_interval", 30)

        while self._running:
            try:
                with self._login_lock:
                    # 检查是否需要跳过（冷却中）
                    if self._cooldown_until and time.time() < self._cooldown_until:
                        self.login_status = "等待重试"
                        self.login_next_retry = f"冷却中..."
                        time.sleep(5)
                        continue

                    # 检查网络状态
                    gateway = self.net_monitor.get_gateway()
                    if not gateway:
                        self.login_status = "等待网络"
                        time.sleep(5)
                        continue

                    # 只检查是否在线（带重试，消除登录成功后的延迟误判）
                    is_online = self.srun_login.check_online(retry=True)
                    if is_online:
                        self.login_status = "登录成功"
                        self.login_retry_count = 0
                        self.login_retry_left = max_retry
                        self.login_next_retry = ""
                        time.sleep(check_interval)
                        continue

                    # 不在线 → 执行登录
                    self.login_status = "登录中"
                    result = self.srun_login.login()

                    if result["success"]:
                        self.login_status = "登录成功"
                        self.login_retry_count = 0
                        self.login_retry_left = max_retry
                        self.login_next_retry = ""
                        self._last_login_attempt = time.time()
                        # 通知托盘
                        self.tray.show_balloon("登录成功", "校园网已自动登录")
                    else:
                        self.login_retry_count += 1
                        self.login_retry_left = max_retry - self.login_retry_count

                        if self.login_retry_count >= max_retry:
                            # 进入冷却
                            self.login_status = "等待重试"
                            self._cooldown_until = time.time() + cooldown
                            self._in_cooldown = True
                            self.login_retry_count = 0
                            self.login_retry_left = max_retry
                            self.login_next_retry = f"{cooldown // 60}分{cooldown % 60}秒后"
                            self.tray.show_balloon("登录失败", f"已重试{max_retry}次，等待{cooldown // 60}分钟后重试")
                            time.sleep(cooldown)
                            self._in_cooldown = False
                            self._cooldown_until = 0
                        else:
                            self.login_status = "登录失败"
                            self.login_next_retry = f"第{self.login_retry_count + 1}次"
                            time.sleep(3)  # 单次间隔 3秒

            except Exception as e:
                logger.error("登录线程异常: %s", e)
                time.sleep(5)

    @safe_thread
    def _network_monitor_worker(self):
        """网络监控线程：持续检测网络状态"""
        while self._running:
            try:
                self.net_monitor.check_network()
                time.sleep(2)
            except Exception:
                time.sleep(2)

    @safe_thread
    def _traffic_worker(self):
        """流量统计线程"""
        while self._running:
            try:
                self.traffic.update()
                time.sleep(1)
            except Exception:
                time.sleep(1)

    @safe_thread
    def _keepalive_worker(self):
        """保活线程"""
        ping_interval = self.config.get("keepalive_ping_interval", 30)
        http_interval = self.config.get("keepalive_http_interval", 120)
        ping_count = 0

        while self._running:
            try:
                gateway = self.net_monitor.get_gateway()
                if gateway:
                    ping_count += 1
                    self.optimizer.keepalive_ping(gateway)

                    # HTTP 保活（每 http_interval / ping_interval 次）
                    if ping_count >= (http_interval // ping_interval):
                        portal = self.config["portal_url"] + self.config["login_page"]
                        self.optimizer.keepalive_http(portal)
                        ping_count = 0

                time.sleep(ping_interval)
            except Exception:
                time.sleep(ping_interval)

    @safe_thread
    def _process_cleaner_worker(self):
        """进程清理线程"""
        while self._running:
            try:
                ProcessCleaner.cleanup_edge()
                time.sleep(60)
            except Exception:
                time.sleep(60)

    # ============ 生命周期 ============

    def start(self):
        """启动应用"""
        self._running = True

        # 注册看门狗线程
        self.watchdog.register("network_monitor", self._network_monitor_worker)
        self.watchdog.register("login", self._login_worker)
        self.watchdog.register("traffic", self._traffic_worker)
        self.watchdog.register("keepalive", self._keepalive_worker)
        self.watchdog.register("cleaner", self._process_cleaner_worker)

        # 启动所有线程
        self.watchdog.start_all()

        # 显示托盘
        self.tray.set_handlers(
            on_double_click=lambda: self.panel.show(),
            on_quit=lambda: self.stop()
        )
        self.tray.set_relogin_handler(self.manual_relogin)
        self.tray.set_optimize_handler(self.manual_optimize)
        self.tray.show()

        # 面板回调
        self.panel.set_optimize_callback(self.manual_optimize)
        self.panel.set_restore_callback(self.manual_restore)
        self.panel.set_relogin_callback(self.manual_relogin)

        logger.info("校园网登录助手已启动")

        # 显示启动通知
        self.tray.show_balloon("已启动", "校园网登录助手正在后台运行")

        # 消息循环
        self.tray.run_message_loop()

    def stop(self):
        """停止应用"""
        logger.info("正在停止...")
        self._running = False
        self.watchdog.stop()
        self.panel.close()
        self.tray.hide()
        logger.info("已停止")

    def manual_relogin(self):
        """手动触发立即重登"""
        logger.info("手动触发重新登录")
        with self._login_lock:
            self._cooldown_until = 0
            self._in_cooldown = False
            self.login_retry_count = 0
            self.login_retry_left = self.config.get("retry_max", 5)
            self.login_status = "手动触发"
            self.login_next_retry = ""

    def manual_optimize(self):
        """手动触发一键优化"""
        logger.info("手动触发一键优化")
        self.tray.show_balloon("优化中", "正在应用网络优化...")
        results = self.optimizer.apply_all()
        success_count = sum(1 for r in results if r["success"])
        self.tray.show_balloon(
            "优化完成",
            f"成功 {success_count}/{len(results)} 项，可点击「一键还原」恢复"
        )

    def manual_restore(self):
        """手动触发一键还原"""
        logger.info("手动触发一键还原")
        self.optimizer.restore_all()
        self.tray.show_balloon("已还原", "所有优化已恢复原始设置")


def main():
    """主入口"""
    # 初始化日志
    setup_logging()

    logger.info("=== 校园网登录助手 ===")

    # 检查并请求管理员权限
    if not is_admin():
        logger.info("需要管理员权限，正在提权...")
        elevate()
        return  # elevate 会启动新进程后退出

    logger.info("管理员权限已获取")

    # 检查配置文件
    config_path = os.path.join(BASE_DIR, "config.json")
    if not os.path.exists(config_path):
        logger.error("config.json 不存在!")
        # 尝试从模板复制
        example_path = os.path.join(BASE_DIR, "config.example.json")
        if os.path.exists(example_path):
            import shutil, codecs
            # 读取模板（可能带 BOM）并写入无 BOM 副本
            with codecs.open(example_path, "r", encoding="utf-8-sig") as fr:
                raw = fr.read()
            with open(config_path, "w", encoding="utf-8") as fw:
                fw.write(raw)
            logger.info("已从 config.example.json 复制配置（已去除 BOM）")
        else:
            logger.error("请创建 config.json 配置文件")
            ctypes.windll.user32.MessageBoxW(
                None, "config.json 配置文件不存在！\n请将 config.example.json 重命名为 config.json 并填写账号密码。", "配置错误", 0
            )
            sys.exit(1)

    # 单例检测（Windows Mutex）
    try:
        import ctypes
        mutex_name = "Global\\CampusNetLoginAssistant_" + str(uuid.uuid4())
        # 使用固定名称
        mutex_name = "Global\\CampusNetLoginAssistant"
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        if mutex and ctypes.windll.kernel32.GetLastError() == 0xB7:  # ERROR_ALREADY_EXISTS
            logger.warning("程序已在运行")
            ctypes.windll.kernel32.CloseHandle(mutex)
            # 显示提示
            ctypes.windll.user32.MessageBoxW(
                None, "校园网登录助手已在运行！", "提示", 0
            )
            return
    except Exception as e:
        logger.warning("单例检测失败: %s", e)

    # 启动应用
    app = CampusNetApp(config_path)

    # 开机自启（仅在首次或配置启用时）
    if app.config.get("auto_start", True):
        if not check_auto_start():
            set_auto_start(True)

    try:
        app.start()
    except KeyboardInterrupt:
        logger.info("用户中断")
        app.stop()
    except Exception as e:
        logger.error("应用异常: %s", e)
        import traceback
        tb = traceback.format_exc()
        logger.error(tb)
        # 弹窗显示错误（无控制台时用户可见）
        try:
            ctypes.windll.user32.MessageBoxW(
                None, f"程序运行出错：\n{e}\n\n详情见日志文件：\n{os.path.join(os.path.dirname(sys.executable) if getattr(sys,"frozen",False) else BASE_DIR, "data", "crash.log")}", "错误", 0
            )
        except:
            pass
        app.stop()


if __name__ == "__main__":
    main()
