"""
监控面板 UI 模块
tkinter 实现，6 个区域展示全部数据，每秒刷新
"""
import tkinter as tk
from tkinter import ttk
import logging
import threading
import time
from core.traffic_stats import TrafficStats

logger = logging.getLogger("CampusNet.UI")


class MonitorPanel:
    """主监控面板窗口"""

    def __init__(self, data_provider):
        """
        data_provider: 提供所有数据的回调对象
            需要实现: get_network_info(), get_speed_info(), get_traffic_info(),
                      get_system_info(), get_login_info(), get_optimize_info()
        """
        self.dp = data_provider
        self._window = None
        self._root = None
        self._visible = False
        self._stop = False
        self._widgets = {}  # 存储所有显示控件
        self._refresh_started = False
        self._credential_callback = None

    def toggle(self):
        """切换显示/隐藏"""
        if self._visible:
            self.hide()
        else:
            self.show()

    def show(self):
        """显示窗口"""
        try:
            self._stop = False
            if self._window is None:
                self._build_window()
            if self._window and self._window.winfo_exists():
                self._window.state("normal")
                self._window.deiconify()
                self._window.lift()
                self._window.attributes("-topmost", True)
                self._window.after(300, lambda: self._window.attributes("-topmost", False))
                self._window.focus_force()
                self._visible = True
                self._start_refresh()
                self.pump_events()
                if not getattr(self.dp, "credentials_configured", True):
                    self._show_credential_dialog()
        except Exception as e:
            logger.error("打开面板失败: %s", e)

    def initialize_hidden(self):
        """预创建隐藏窗口，避免托盘点击后才初始化 Tk 导致窗口打不开。"""
        try:
            if self._window is None:
                self._build_window()
                self._window.withdraw()
                self._visible = False
        except Exception as e:
            logger.error("初始化监控面板失败: %s", e)

    def hide(self):
        """隐藏窗口"""
        try:
            if self._window:
                self._window.withdraw()
        except:
            pass
        self._visible = False

    def close(self):
        """关闭窗口"""
        self._stop = True
        if self._window:
            try:
                self._window.destroy()
            except:
                pass
            self._window = None
        if self._root:
            try:
                self._root.destroy()
            except:
                pass
            self._root = None
        self._visible = False
        self._refresh_started = False

    def is_visible(self) -> bool:
        return self._visible

    def _build_window(self):
        """构建窗口布局"""
        if not tk._default_root:
            self._root = tk.Tk()
            self._root.withdraw()
        else:
            self._root = tk._default_root
        self._window = tk.Toplevel()
        self._window.title("校园网登录助手 - 监控面板")
        self._window.geometry("900x680")
        self._window.minsize(800, 600)
        self._window.protocol("WM_DELETE_WINDOW", self.hide)
        self._window.configure(bg="#f0f0f0")

        # 设置窗口样式
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("微软雅黑", 11, "bold"), padding=5)
        style.configure("Value.TLabel", font=("微软雅黑", 10), padding=2)
        style.configure("Status.TLabel", font=("微软雅黑", 12, "bold"), padding=5)
        style.configure("Section.TLabelframe", font=("微软雅黑", 10, "bold"), padding=5)

        # 主容器
        main_frame = ttk.Frame(self._window, padding=5)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ---- 第一行：网络基础 + 登录状态 ----
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=2)

        # 区域1：网络基础
        net_frame = ttk.LabelFrame(top_frame, text="🖧 网络基础", width=440, height=150)
        net_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        net_frame.pack_propagate(False)

        self._widgets["net"] = {}
        net_items = [
            ("网口名称", "adapter"),
            ("MAC 地址", "mac"),
            ("本机 IPv4", "ipv4"),
            ("子网掩码", "mask"),
            ("默认网关", "gateway"),
            ("DNS 地址", "dns"),
            ("接入类型", "media_type"),
        ]
        for i, (label, key) in enumerate(net_items):
            lbl = ttk.Label(net_frame, text=f"{label}:", style="Value.TLabel")
            lbl.grid(row=i, column=0, sticky=tk.W, padx=5, pady=1)
            val = ttk.Label(net_frame, text="--", style="Value.TLabel", foreground="#333")
            val.grid(row=i, column=1, sticky=tk.W, padx=5, pady=1)
            self._widgets["net"][key] = val

        # 区域2：登录状态
        login_frame = ttk.LabelFrame(top_frame, text="🔐 登录状态", width=440, height=150)
        login_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=2)
        login_frame.pack_propagate(False)

        self._widgets["login"] = {}
        login_items = [
            ("网络状态", "net_status"),
            ("登录状态", "login_status"),
            ("重试剩余", "retry_left"),
            ("下次重试", "next_retry"),
        ]
        for i, (label, key) in enumerate(login_items):
            lbl = ttk.Label(login_frame, text=f"{label}:", style="Value.TLabel")
            lbl.grid(row=i, column=0, sticky=tk.W, padx=5, pady=5)
            val = ttk.Label(login_frame, text="--", style="Status.TLabel")
            val.grid(row=i, column=1, sticky=tk.W, padx=5, pady=5)
            self._widgets["login"][key] = val

        # ---- 第二行：速率链路 + 流量统计 ----
        mid_frame = ttk.Frame(main_frame)
        mid_frame.pack(fill=tk.X, pady=2)

        # 区域3：速率链路
        speed_frame = ttk.LabelFrame(mid_frame, text="📊 速率与链路", width=440, height=130)
        speed_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        speed_frame.pack_propagate(False)

        self._widgets["speed"] = {}
        speed_items = [
            ("实时上行", "up_speed"),
            ("实时下行", "down_speed"),
            ("协商带宽", "link_speed"),
            ("网关延迟", "latency"),
            ("丢包率", "loss"),
        ]
        for i, (label, key) in enumerate(speed_items):
            lbl = ttk.Label(speed_frame, text=f"{label}:", style="Value.TLabel")
            lbl.grid(row=i, column=0, sticky=tk.W, padx=5, pady=2)
            val = ttk.Label(speed_frame, text="--", style="Value.TLabel", foreground="#333")
            val.grid(row=i, column=1, sticky=tk.W, padx=5, pady=2)
            self._widgets["speed"][key] = val

        # 区域4：流量统计
        traffic_frame = ttk.LabelFrame(mid_frame, text="📈 流量统计", width=440, height=130)
        traffic_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=2)
        traffic_frame.pack_propagate(False)

        self._widgets["traffic"] = {}
        traffic_items = [
            ("本次上行", "session_up"),
            ("本次下行", "session_down"),
            ("本次总流量", "session_total"),
            ("今日上行", "daily_up"),
            ("今日下行", "daily_down"),
            ("今日总流量", "daily_total"),
        ]
        for i, (label, key) in enumerate(traffic_items):
            lbl = ttk.Label(traffic_frame, text=f"{label}:", style="Value.TLabel")
            lbl.grid(row=i, column=0, sticky=tk.W, padx=5, pady=1)
            val = ttk.Label(traffic_frame, text="--", style="Value.TLabel", foreground="#333")
            val.grid(row=i, column=1, sticky=tk.W, padx=5, pady=1)
            self._widgets["traffic"][key] = val

        # ---- 第三行：主机系统 + 网络优化 ----
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.BOTH, expand=True, pady=2)

        # 区域5：主机系统
        sys_frame = ttk.LabelFrame(bottom_frame, text="🖥 主机系统", width=440, height=200)
        sys_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        sys_frame.pack_propagate(False)

        self._widgets["sys"] = {}
        sys_items = [
            ("计算机名", "computer_name"),
            ("用户", "user_name"),
            ("系统版本", "os_version"),
            ("开机时长", "uptime"),
        ]
        for i, (label, key) in enumerate(sys_items):
            lbl = ttk.Label(sys_frame, text=f"{label}:", style="Value.TLabel")
            lbl.grid(row=i, column=0, sticky=tk.W, padx=5, pady=3)
            val = ttk.Label(sys_frame, text="--", style="Value.TLabel", foreground="#333")
            val.grid(row=i, column=1, sticky=tk.W, padx=5, pady=3)
            self._widgets["sys"][key] = val

        # CPU 进度条
        ttk.Label(sys_frame, text="CPU:", style="Value.TLabel").grid(
            row=4, column=0, sticky=tk.W, padx=5, pady=3)
        self._widgets["sys"]["cpu_progress"] = ttk.Progressbar(
            sys_frame, length=200, mode="determinate")
        self._widgets["sys"]["cpu_progress"].grid(row=4, column=1, padx=5, pady=3, sticky=tk.W)
        self._widgets["sys"]["cpu_label"] = ttk.Label(
            sys_frame, text="--", style="Value.TLabel", width=8)
        self._widgets["sys"]["cpu_label"].grid(row=4, column=2, padx=2, pady=3)

        # 内存进度条
        ttk.Label(sys_frame, text="内存:", style="Value.TLabel").grid(
            row=5, column=0, sticky=tk.W, padx=5, pady=3)
        self._widgets["sys"]["mem_progress"] = ttk.Progressbar(
            sys_frame, length=200, mode="determinate")
        self._widgets["sys"]["mem_progress"].grid(row=5, column=1, padx=5, pady=3, sticky=tk.W)
        self._widgets["sys"]["mem_label"] = ttk.Label(
            sys_frame, text="--", style="Value.TLabel", width=20)
        self._widgets["sys"]["mem_label"].grid(row=5, column=2, padx=2, pady=3)

        # 区域6：网络优化
        opt_frame = ttk.LabelFrame(bottom_frame, text="⚡ 网络优化", width=440, height=200)
        opt_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=2)
        opt_frame.pack_propagate(False)

        self._widgets["opt"] = {}
        opt_items = [
            ("实际带宽", "bandwidth"),
            ("MTU 路径", "mtu"),
            ("DNS 最佳", "dns_best"),
            ("网卡节能", "power_save"),
            ("TCP 状态", "tcp_state"),
            ("网络配置", "net_profile"),
        ]
        for i, (label, key) in enumerate(opt_items):
            lbl = ttk.Label(opt_frame, text=f"{label}:", style="Value.TLabel")
            lbl.grid(row=i, column=0, sticky=tk.W, padx=5, pady=3)
            val = ttk.Label(opt_frame, text="--", style="Value.TLabel", foreground="#333")
            val.grid(row=i, column=1, sticky=tk.W, padx=5, pady=3)
            self._widgets["opt"][key] = val

        # 优化按钮
        btn_frame = ttk.Frame(opt_frame)
        btn_frame.grid(row=len(opt_items), column=0, columnspan=2, pady=5)
        self._btn_optimize = ttk.Button(
            btn_frame, text="一键优化", command=self._on_optimize_click)
        self._btn_optimize.pack(side=tk.LEFT, padx=5)
        self._btn_restore = ttk.Button(
            btn_frame, text="一键还原", command=self._on_restore_click)
        self._btn_restore.pack(side=tk.LEFT, padx=5)
        self._btn_relogin = ttk.Button(
            btn_frame, text="立即重登", command=self._on_relogin_click)
        self._btn_relogin.pack(side=tk.LEFT, padx=5)

        # 优化回调
        self._optimize_callback = None
        self._restore_callback = None
        self._relogin_callback = None

    def set_optimize_callback(self, cb):
        self._optimize_callback = cb

    def set_restore_callback(self, cb):
        self._restore_callback = cb

    def set_relogin_callback(self, cb):
        self._relogin_callback = cb

    def set_credential_callback(self, cb):
        self._credential_callback = cb

    def _show_credential_dialog(self):
        """首次运行时引导填写账号密码。"""
        if not self._window or getattr(self, "_credential_dialog_open", False):
            return
        self._credential_dialog_open = True
        dialog = tk.Toplevel(self._window)
        dialog.title("首次配置校园网账号")
        dialog.geometry("360x190")
        dialog.resizable(False, False)
        dialog.transient(self._window)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="请填写校园网账号和密码，保存后会自动登录。").grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10)
        )
        ttk.Label(frame, text="账号：").grid(row=1, column=0, sticky=tk.E, pady=4)
        username_var = tk.StringVar(value=getattr(self.dp, "config", {}).get("username", ""))
        username_entry = ttk.Entry(frame, textvariable=username_var, width=28)
        username_entry.grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="密码：").grid(row=2, column=0, sticky=tk.E, pady=4)
        password_var = tk.StringVar(value=getattr(self.dp, "config", {}).get("password", ""))
        password_entry = ttk.Entry(frame, textvariable=password_var, width=28, show="*")
        password_entry.grid(row=2, column=1, sticky=tk.W, pady=4)

        status_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=status_var, foreground="#c62828").grid(
            row=3, column=0, columnspan=2, sticky=tk.W, pady=(4, 0)
        )

        def on_save():
            username = username_var.get().strip()
            password = password_var.get().strip()
            if not username or not password:
                status_var.set("账号和密码不能为空")
                return
            if self._credential_callback:
                ok, message = self._credential_callback(username, password)
                if not ok:
                    status_var.set(message or "保存失败")
                    return
            self._credential_dialog_open = False
            dialog.destroy()

        def on_close():
            self._credential_dialog_open = False
            dialog.destroy()

        btns = ttk.Frame(frame)
        btns.grid(row=4, column=0, columnspan=2, pady=12)
        ttk.Button(btns, text="保存并登录", command=on_save).pack(side=tk.LEFT, padx=5)
        ttk.Button(btns, text="稍后填写", command=on_close).pack(side=tk.LEFT, padx=5)
        dialog.protocol("WM_DELETE_WINDOW", on_close)
        username_entry.focus_set()

    def _on_optimize_click(self):
        if self._optimize_callback:
            threading.Thread(target=self._optimize_callback, daemon=True).start()

    def _on_restore_click(self):
        if self._restore_callback:
            threading.Thread(target=self._restore_callback, daemon=True).start()

    def _on_relogin_click(self):
        if self._relogin_callback:
            threading.Thread(target=self._relogin_callback, daemon=True).start()

    def _start_refresh(self):
        """启动 UI 刷新循环"""
        if self._stop or self._refresh_started:
            return
        self._refresh_started = True

        def refresh():
            try:
                if not self._visible or self._stop:
                    self._refresh_started = False
                    return
                self._update_all()
            except Exception as e:
                logger.debug("UI 刷新异常: %s", e)
            try:
                if not self._stop and self._window and self._window.winfo_exists():
                    self._window.after(1000, refresh)
            except:
                pass

        self._window.after(1000, refresh)

    def pump_events(self):
        """由托盘消息循环调用，驱动 Tk 事件，避免面板无 mainloop 时不刷新。"""
        root = self._root or tk._default_root
        if not root:
            return
        try:
            root.update_idletasks()
            root.update()
        except tk.TclError:
            self._window = None
            self._root = None
            self._visible = False
            self._refresh_started = False

    def schedule(self, callback, delay_ms: int = 0):
        """在 Tk 主线程中执行回调。"""
        root = self._root or tk._default_root
        if root:
            root.after(delay_ms, callback)

    def mainloop(self):
        """运行 Tk 主事件循环。"""
        root = self._root or tk._default_root
        if root:
            root.mainloop()

    def quit_loop(self):
        """退出 Tk 主事件循环。"""
        root = self._root or tk._default_root
        if root:
            try:
                root.quit()
            except tk.TclError:
                pass

    def _update_all(self):
        """更新所有数据"""
        if not self._window or not self._visible:
            return
        try:
            # 更新网络信息
            net = self.dp.get_network_info()
            w = self._widgets["net"]
            w["adapter"].config(text=net.get("adapter", "--"))
            w["mac"].config(text=net.get("mac", "--"))
            w["ipv4"].config(text=net.get("ipv4", "--"))
            w["mask"].config(text=net.get("mask", "--"))
            w["gateway"].config(text=net.get("gateway", "--"))
            w["dns"].config(text=net.get("dns", "--"))
            w["media_type"].config(text=net.get("media_type", "--"))

            # 更新登录状态
            login = self.dp.get_login_info()
            w = self._widgets["login"]

            net_status = login.get("net_status", "检测中")
            net_color = {"网络正常": "#2e7d32", "网络断开": "#c62828", "网络受限": "#e65100"}
            w["net_status"].config(text=net_status, foreground=net_color.get(net_status, "#333"))

            login_status = login.get("login_status", "等待中")
            login_color = {"登录成功": "#2e7d32", "登录中": "#1565c0",
                           "登录失败": "#c62828", "等待重试": "#e65100"}
            w["login_status"].config(text=login_status, foreground=login_color.get(login_status, "#333"))
            w["retry_left"].config(text=str(login.get("retry_left", "--")))
            w["next_retry"].config(text=str(login.get("next_retry", "--")))

            # 更新速率
            speed = self.dp.get_speed_info()
            w = self._widgets["speed"]
            w["up_speed"].config(text=str(speed.get("up", "--")))
            w["down_speed"].config(text=str(speed.get("down", "--")))
            w["link_speed"].config(text=str(speed.get("link", "--")))
            w["latency"].config(text=str(speed.get("latency", "--")))
            w["loss"].config(text=str(speed.get("loss", "--")))

            # 更新流量
            traffic = self.dp.get_traffic_info()
            w = self._widgets["traffic"]
            w["session_up"].config(text=str(traffic.get("session_up", "--")))
            w["session_down"].config(text=str(traffic.get("session_down", "--")))
            w["session_total"].config(text=str(traffic.get("session_total", "--")))
            w["daily_up"].config(text=str(traffic.get("daily_up", "--")))
            w["daily_down"].config(text=str(traffic.get("daily_down", "--")))
            w["daily_total"].config(text=str(traffic.get("daily_total", "--")))

            # 更新系统信息
            sys_info = self.dp.get_system_info()
            w = self._widgets["sys"]
            w["computer_name"].config(text=str(sys_info.get("computer_name", "--")))
            w["user_name"].config(text=str(sys_info.get("user_name", "--")))
            w["os_version"].config(text=str(sys_info.get("os_version", "--")))
            w["uptime"].config(text=str(sys_info.get("uptime", "--")))

            cpu = sys_info.get("cpu_percent", 0)
            w["cpu_progress"].config(value=cpu)
            w["cpu_label"].config(text=f"{cpu:.1f}%")

            mem_pct = sys_info.get("mem_percent", 0)
            mem_used = sys_info.get("mem_used", 0)
            mem_total = sys_info.get("mem_total", 0)
            w["mem_progress"].config(value=mem_pct)
            
            w["mem_label"].config(
                text=f"{TrafficStats.format_bytes(mem_used)} / {TrafficStats.format_bytes(mem_total)}")

            # 更新网络优化
            opt = self.dp.get_optimize_info()
            w = self._widgets["opt"]
            w["bandwidth"].config(text=str(opt.get("bandwidth", "--")))
            w["mtu"].config(text=str(opt.get("mtu", "--")))
            w["dns_best"].config(text=str(opt.get("dns_best", "--")))
            w["power_save"].config(text=str(opt.get("power_save", "--")))
            w["tcp_state"].config(text=str(opt.get("tcp_state", "--")))
            w["net_profile"].config(text=str(opt.get("net_profile", "--")))

        except Exception as e:
            logger.debug("数据更新异常: %s", e)
