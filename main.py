"""
校园网登录助手 - 主入口
单例检测 → 管理员提权 → 加载配置 → 启动各线程 → 托盘驻留
"""
import ctypes
import json
import logging
import os
import queue
import sys
import threading
import time

from utils.paths import app_base_dir, bundled_dir, config_path as default_config_path, data_dir

# 路径适配
BASE_DIR = app_base_dir()
MEIPASS_DIR = bundled_dir()
sys.path.insert(0, BASE_DIR)
DATA_DIR = data_dir()

from core.anti_crash import setup_logging, safe_thread, Watchdog, ProcessCleaner
from core.network_monitor import (
    NetworkMonitor,
    NETWORK_OK,
    NETWORK_DISCONNECTED,
    NETWORK_LIMITED,
)
from core.srun_login import SrunLogin
from core.network_optimizer import NetworkOptimizer
from core.system_info import SystemInfo
from core.traffic_stats import TrafficStats
from ui.tray import SysTrayIcon
from ui.monitor_panel import MonitorPanel
from utils.admin import is_admin, elevate, set_auto_start, check_auto_start

logger = logging.getLogger("CampusNet.Main")
_INSTANCE_LOCK_HANDLE = None
_INSTANCE_MUTEX_NAME = "Global\\CampusNetLoginAssistant_StudentNet"


def ensure_config_file() -> str:
    """确保用户目录存在配置文件，避免安装目录不可写导致启动异常。"""
    config_file = default_config_path()
    if os.path.exists(config_file):
        return config_file

    candidates = [
        os.path.join(BASE_DIR, "config.json"),
        os.path.join(MEIPASS_DIR, "config.example.json"),
        os.path.join(BASE_DIR, "config.example.json"),
    ]
    for candidate in candidates:
        if not os.path.exists(candidate):
            continue
        try:
            import codecs
            with codecs.open(candidate, "r", encoding="utf-8-sig") as fr:
                raw = fr.read()
            with open(config_file, "w", encoding="utf-8") as fw:
                fw.write(raw)
            logger.info("配置已复制到用户目录: %s", config_file)
            return config_file
        except Exception as e:
            logger.warning("复制配置失败 [%s]: %s", candidate, e)

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
    with open(config_file, "w", encoding="utf-8") as fw:
        json.dump(default_config, fw, ensure_ascii=False, indent=2)
    logger.info("已创建默认配置: %s", config_file)
    return config_file


def acquire_single_instance_lock() -> bool:
    """用 Windows Mutex 实现单例，避免重复启动多个后台实例。"""
    global _INSTANCE_LOCK_HANDLE
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, _INSTANCE_MUTEX_NAME)
        last_error = kernel32.GetLastError()
        if not handle:
            logger.warning("创建单例互斥体失败: %s", last_error)
            return True
        if last_error == 183:
            kernel32.CloseHandle(handle)
            return False
        _INSTANCE_LOCK_HANDLE = handle
        return True
    except Exception as e:
        logger.warning("单例互斥体失败: %s", e)
        return True


def should_show_panel() -> bool:
    """判断本次启动是否应显示监控面板。"""
    args = {arg.lower() for arg in sys.argv[1:]}
    return "--show" in args or "/show" in args


def is_background_start() -> bool:
    """判断是否由开机自启任务以后台模式启动。"""
    args = {arg.lower() for arg in sys.argv[1:]}
    return "--background" in args or "/background" in args


def launch_requests_panel() -> bool:
    """手动启动默认显示面板，开机后台任务不显示。"""
    return should_show_panel() or not is_background_start()


def bring_existing_panel_to_front() -> bool:
    """重复启动时唤醒已运行实例的面板。"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "校园网登录助手 - 监控面板")
        if hwnd:
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            return True

        # 已有实例可能处于后台，面板没有可见 HWND；通过托盘隐藏窗口投递显示消息。
        show_message = 0x0400 + 101
        for _ in range(10):
            tray_hwnd = user32.FindWindowW("CampusNetTrayWindow", None)
            if tray_hwnd:
                user32.PostMessageW(tray_hwnd, show_message, 0, 0)
                return True
            time.sleep(0.1)
        return False
    except Exception as e:
        logger.debug("唤醒已有窗口失败: %s", e)
        return False


class CampusNetApp:
    """主应用类：协调所有模块"""

    def __init__(self, config_path: str = None):
        # 加载配置
        if config_path is None:
            config_path = default_config_path()
        self.config = self._load_config(config_path)
        self.config_path = config_path
        self.credentials_configured = bool(
            self.config.get("username", "").strip()
            and self.config.get("password", "").strip()
        )

        # 初始化各模块
        self.net_monitor = NetworkMonitor()
        self.srun_login = SrunLogin(self.config, self.net_monitor)
        self.optimizer = NetworkOptimizer()
        self.sys_info = SystemInfo()
        self.traffic = TrafficStats()

        # 登录状态
        self.login_status = "等待中" if self.credentials_configured else "等待配置"
        self.login_retry_count = 0
        self.login_retry_left = self.config.get("retry_max", 5)
        self.login_next_retry = ""
        self.network_status = NETWORK_DISCONNECTED
        self.campus_network = False
        self.campus_network_reason = "尚未检测"
        self.gateway_latency = 0.0
        self.packet_loss = 100.0
        self._login_lock = threading.Lock()
        self._last_login_attempt = 0
        self._last_login_success = 0
        self._in_cooldown = False
        self._cooldown_until = 0

        # 系统静态信息
        self._sys_static = SystemInfo.get_static_info()

        # 网络信息缓存
        self._net_info = {}
        self._net_cache_ts = 0
        self._net_cache_interval = 5
        self._speed_info = {}
        self._opt_info = {}
        self._opt_cache_ts = 0
        self._opt_cache_interval = 120  # 秒
        self._opt_refreshing = False
        self._opt_lock = threading.Lock()

        # UI
        self.tray = SysTrayIcon("校园网登录助手")
        self.panel = MonitorPanel(self)
        self._ui_actions = queue.Queue()

        # 看门狗
        self.watchdog = Watchdog(check_interval=30)

        # 运行标志
        self._running = False

    def _post_ui_action(self, action):
        """把托盘回调转成主循环任务，避免在 Win32 回调里直接操作 Tk。"""
        logger.debug("投递 UI 任务: %s", getattr(action, "__name__", action))
        self._ui_actions.put(action)

    def _run_ui_actions(self):
        """执行托盘投递的 UI 任务。"""
        while True:
            try:
                action = self._ui_actions.get_nowait()
            except queue.Empty:
                break
            try:
                logger.debug("执行 UI 任务: %s", getattr(action, "__name__", action))
                action()
            except Exception as e:
                logger.error("UI 任务执行失败: %s", e)

    def save_credentials(self, username: str, password: str):
        """保存校园网账号密码，并立即唤醒登录线程。"""
        try:
            self.config["username"] = username
            self.config["password"] = password
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)

            self.credentials_configured = True
            self.srun_login.username = username
            self.srun_login.password = password
            with self._login_lock:
                self._cooldown_until = 0
                self._in_cooldown = False
                self.login_retry_count = 0
                self.login_retry_left = self.config.get("retry_max", 5)
                self.login_next_retry = ""
                self.login_status = "等待登录"
            logger.info("校园网账号配置已保存")
            return True, "已保存"
        except Exception as e:
            logger.error("保存账号配置失败: %s", e)
            return False, str(e)

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
        now = time.time()
        if self._net_info and now - self._net_cache_ts < self._net_cache_interval:
            return self._net_info
        try:
            import subprocess

            active = self.net_monitor.get_active_interface()
            dns = "--"

            # 获取 DNS
            try:
                dns_result = subprocess.run(
                    ["nslookup", "baidu.com"],
                    capture_output=True, text=True, timeout=2, creationflags=0x08000000
                )
                for line in dns_result.stdout.splitlines():
                    if "Address:" in line and "192.168" not in line and "#53" not in line:
                        dns = line.split("Address:")[-1].strip()
                        break
            except Exception:
                pass

            self._net_info = {
                "adapter": active.get("adapter") or "--",
                "mac": active.get("mac") or "--",
                "ipv4": active.get("ipv4") or "--",
                "mask": active.get("mask") or "--",
                "gateway": active.get("gateway") or self.net_monitor.get_gateway() or "--",
                "dns": dns,
                "media_type": active.get("media_type") or "--",
            }
            self._net_cache_ts = now
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
            latency = f"{self.gateway_latency:.1f} ms" if self.gateway_latency > 0 else "--"
            loss = f"{self.packet_loss:.0f}%" if self.packet_loss >= 0 else "--"

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
        # 倒计时
        next_retry = self.login_next_retry
        if self._cooldown_until and time.time() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.time())
            next_retry = f"{remaining // 60}分{remaining % 60}秒后"

        return {
            "net_status": self.network_status,
            "campus_status": "已识别校园网" if self.campus_network else self.campus_network_reason,
            "login_status": self.login_status,
            "retry_left": str(self.login_retry_left),
            "next_retry": next_retry,
            "edge_status": "未使用",
        }

    def get_optimize_info(self) -> dict:
        """提供给 UI 的优化信息；慢检测在后台刷新，避免卡住 Tk 主线程。"""
        now = time.time()
        if not self._opt_info:
            self._opt_info = {
                "bandwidth": "检测中",
                "mtu": "检测中",
                "dns_best": "检测中",
                "power_save": "检测中",
                "tcp_state": "检测中",
                "net_profile": "检测中",
            }
        if now - self._opt_cache_ts >= self._opt_cache_interval and not self._opt_refreshing:
            threading.Thread(target=self._refresh_optimize_info, daemon=True).start()
        return dict(self._opt_info)

    def _refresh_optimize_info(self):
        """后台刷新网络优化状态，避免阻塞 UI。"""
        with self._opt_lock:
            if self._opt_refreshing:
                return
            self._opt_refreshing = True
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
            self._opt_cache_ts = time.time()
        except Exception as e:
            logger.debug("优化信息采集异常: %s", e)
        finally:
            self._opt_refreshing = False


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
                    if not self.credentials_configured:
                        self.login_status = "等待配置"
                        self.login_retry_count = 0
                        self.login_retry_left = max_retry
                        self.login_next_retry = "请填写 config.json"
                        time.sleep(10)
                        continue

                    if self._last_login_success and time.time() - self._last_login_success < 180:
                        self.login_status = "登录成功"
                        self.login_retry_count = 0
                        self.login_retry_left = max_retry
                        self.login_next_retry = ""
                        time.sleep(5)
                        continue

                    # 检查是否需要跳过（冷却中）
                    if self._cooldown_until and time.time() < self._cooldown_until:
                        self.login_status = "等待重试"
                        self.login_next_retry = f"冷却中..."
                        time.sleep(5)
                        continue

                    # 检查网络状态
                    if not self.campus_network:
                        self.login_status = "非校园网，已暂停"
                        self.login_next_retry = "检测到校园网后自动恢复"
                        time.sleep(5)
                        continue

                    # 只有校园网且外网受限时才允许发起认证。
                    if self.network_status == NETWORK_DISCONNECTED:
                        self.login_status = "等待网络"
                        self.login_next_retry = "网卡或网关不可用"
                        time.sleep(5)
                        continue

                    gateway = self.net_monitor.get_gateway()
                    if not gateway:
                        self.login_status = "等待网络"
                        self.login_next_retry = "等待默认网关"
                        time.sleep(5)
                        continue

                    if self.network_status == NETWORK_OK:
                        self.login_status = "网络正常，跳过登录"
                        self.login_next_retry = "仅在校园网受限时认证"
                        time.sleep(check_interval)
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
                        self._last_login_success = time.time()
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
                status, latency, loss = self.net_monitor.check_network()
                self.network_status = status
                self.gateway_latency = latency
                self.packet_loss = loss
                self.campus_network, self.campus_network_reason = self.net_monitor.check_campus_network(
                    self.config.get("portal_url", ""),
                    self.config.get("login_page", ""),
                )
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

    @safe_thread
    def _maintenance_worker(self):
        """长期驻留维护线程：定期 GC 和整理工作集。"""
        while self._running:
            try:
                ProcessCleaner.cleanup_runtime()
                time.sleep(300)
            except Exception:
                time.sleep(300)

    def start(self):
        """启动应用，Tk 主循环留在主线程运行。"""
        self._running = True

        self.watchdog.register("network_monitor", self._network_monitor_worker)
        self.watchdog.register("login", self._login_worker)
        self.watchdog.register("traffic", self._traffic_worker)
        self.watchdog.register("keepalive", self._keepalive_worker)
        self.watchdog.register("maintenance", self._maintenance_worker)

        self.panel.set_optimize_callback(self.manual_optimize)
        self.panel.set_restore_callback(self.manual_restore)
        self.panel.set_relogin_callback(self.manual_relogin)
        self.panel.set_credential_callback(self.save_credentials)
        self.panel.initialize_hidden()

        self.tray.set_handlers(
            on_double_click=lambda: self._post_ui_action(self.panel.show),
            on_quit=lambda: self._post_ui_action(self.stop),
        )
        self.tray.set_relogin_handler(self.manual_relogin)
        self.tray.set_optimize_handler(self.manual_optimize)
        self.tray.set_restore_handler(self.manual_restore)

        def tray_worker():
            try:
                self.tray.show()
                self.tray.run_message_loop()
            except Exception as e:
                logger.error("托盘线程异常: %s", e)

        threading.Thread(target=tray_worker, name="tray", daemon=True).start()
        self.watchdog.start_all()

        logger.info("校园网登录助手已启动")
        if launch_requests_panel():
            self._post_ui_action(self.panel.show)

        def poll_ui_actions():
            self._run_ui_actions()
            if self._running:
                self.panel.schedule(poll_ui_actions, 50)

        self.panel.schedule(poll_ui_actions, 50)
        self.panel.mainloop()

    def stop(self):
        """停止应用"""
        logger.info("正在停止...")
        self._running = False
        self.watchdog.stop()
        self.tray.hide()
        self.panel.close()
        self.panel.quit_loop()
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
            self._last_login_success = 0
            self.login_next_retry = ""

    def manual_optimize(self):
        """手动触发一键优化"""
        logger.info("手动触发一键优化")
        self._opt_info = {
            "bandwidth": "优化中",
            "mtu": "优化中",
            "dns_best": "优化中",
            "power_save": "正在应用",
            "tcp_state": "正在应用",
            "net_profile": "正在应用",
        }
        self._opt_cache_ts = time.time()
        self.tray.show_balloon("优化中", "正在应用网络优化...")
        results = self.optimizer.apply_all()
        success_count = sum(1 for r in results if r["success"])
        failed = [r["message"] for r in results if not r["success"]]
        summary = f"成功 {success_count}/{len(results)} 项"
        if failed:
            summary += f"，失败：{failed[0][:30]}"
        self._opt_info.update({
            "power_save": summary,
            "tcp_state": "已执行，详情见日志",
            "net_profile": "已执行，详情见日志",
        })
        self._opt_cache_ts = 0
        self.tray.show_balloon(
            "优化完成",
            f"{summary}，可点击「一键还原」恢复"
        )

    def manual_restore(self):
        """手动触发一键还原"""
        logger.info("手动触发一键还原")
        self._opt_info.update({
            "power_save": "还原中",
            "tcp_state": "还原中",
            "net_profile": "还原中",
        })
        self.optimizer.restore_all()
        self._opt_cache_ts = 0
        self.tray.show_balloon("已还原", "所有优化已恢复原始设置")


def main():
    """主入口"""
    # 初始化日志
    setup_logging()

    logger.info("=== 校园网登录助手 ===")

    # 打印权限状态（不强制提权）
    if is_admin():
        logger.info("管理员权限已获取")
    else:
        logger.warning("以普通用户权限运行（网络优化需管理员）")

    # 数据目录
    os.makedirs(DATA_DIR, exist_ok=True)

    if not acquire_single_instance_lock():
        logger.warning("程序已在运行")
        if launch_requests_panel():
            bring_existing_panel_to_front()
        return

    # Use per-user config directory; Program Files is not writable for normal users.
    config_path = ensure_config_file()

    app = CampusNetApp(config_path)

    # 开机自启（仅在首次或配置启用时）
    if app.config.get("auto_start", True):
        if is_admin() and not check_auto_start():
            set_auto_start(True)
        elif not is_admin():
            logger.info("普通权限运行，跳过最高权限自启任务检查")

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
                None, f"程序运行出错：\n{e}\n\n详情见日志文件：\n{os.path.join(DATA_DIR, "crash.log")}", "错误", 0
            )
        except:
            pass
        app.stop()


if __name__ == "__main__":
    main()
