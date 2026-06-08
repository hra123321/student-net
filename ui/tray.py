"""
系统托盘模块
使用 win32gui 实现系统托盘图标（比手写 ctypes 更可靠）
"""
import logging
import threading

logger = logging.getLogger("CampusNet.Tray")


class SysTrayIcon:
    """系统托盘图标 - 基于 pywin32"""

    def __init__(self, tooltip: str = "校园网登录助手"):
        self._tooltip = tooltip
        self._hwnd = None
        self._nid = None
        self._running = False
        self._on_quit = None
        self._on_double_click = None
        self._on_relogin = None
        self._on_optimize = None
        self._msg_id = None

    def set_handlers(self, on_double_click=None, on_quit=None):
        self._on_double_click = on_double_click
        self._on_quit = on_quit

    def set_relogin_handler(self, handler):
        self._on_relogin = handler

    def set_optimize_handler(self, handler):
        self._on_optimize = handler

    def _create_hwnd(self):
        """创建隐藏窗口作为托盘消息接收者"""
        import win32gui
        import win32con

        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self._window_proc
        wc.lpszClassName = "CampusNetTrayClass_" + str(id(self))
        wc.hInstance = win32gui.GetModuleHandle(None)
        wc.hCursor = 0
        wc.hbrBackground = 0

        try:
            atom = win32gui.RegisterClass(wc)
        except:
            # 类可能已注册
            pass

        self._hwnd = win32gui.CreateWindow(
            wc.lpszClassName, "CampusNetTray", win32con.WS_OVERLAPPED,
            0, 0, 0, 0, 0, 0, wc.hInstance, None
        )

        if not self._hwnd:
            logger.error("CreateWindow failed")
            return False

        # 自定义消息 ID
        self._msg_id = win32con.WM_USER + 100
        return True

    def _window_proc(self, hwnd, msg, wparam, lparam):
        """窗口消息处理"""
        import win32con

        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0

        if msg == self._msg_id:
            if lparam == win32con.WM_LBUTTONDBLCLK:
                if self._on_double_click:
                    self._on_double_click()
            elif lparam == win32con.WM_RBUTTONDOWN:
                self._show_context_menu()
            elif lparam == win32con.WM_LBUTTONDOWN:
                if self._on_double_click:
                    self._on_double_click()

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _show_context_menu(self):
        """显示右键菜单"""
        import win32gui
        import win32con

        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, 1, "显示面板")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 2, "立即重登")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 3, "一键优化")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 4, "退出")

        pos = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self._hwnd)

        cmd = win32gui.TrackPopupMenu(
            menu, win32con.TPM_LEFTALIGN | win32con.TPM_RETURNCMD,
            pos[0], pos[1], 0, self._hwnd, None
        )

        win32gui.DestroyMenu(menu)
        self._handle_menu_command(cmd)

    def _handle_menu_command(self, cmd: int):
        """处理菜单命令"""
        if cmd == 1 and self._on_double_click:
            self._on_double_click()
        elif cmd == 2 and self._on_relogin:
            self._on_relogin()
        elif cmd == 3 and self._on_optimize:
            self._on_optimize()
        elif cmd == 4:
            if self._on_quit:
                self._on_quit()
            self.hide()

    def show(self):
        """显示托盘图标"""
        import win32gui
        import win32con

        if not self._create_hwnd():
            return

        # 定义图标（使用系统默认应用图标）
        hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

        import win32api
        import struct

        # 创建 NOTIFYICONDATA
        guid = "{CampusNetLogin-" + str(id(self)) + "}"

        flags = win32con.NIF_MESSAGE | win32con.NIF_ICON | win32con.NIF_TIP | 0x20

        self._nid = (self._hwnd, 100, flags, self._msg_id, hicon, self._tooltip[:127], guid)

        # 添加托盘图标
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self._nid)
        except Exception as e:
            logger.error("Shell_NotifyIcon failed: %s", e)
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "系统托盘图标创建失败，请检查系统设置", "提示", 0)
            return

        self._running = True
        logger.info("托盘图标已显示")

    def show_balloon(self, title: str, message: str, timeout_ms: int = 3000):
        """显示气球提示"""
        if not self._running:
            return
        import win32gui
        try:
            win32gui.Shell_NotifyIcon(
                win32gui.NIM_MODIFY,
                (self._nid[0], self._nid[1], self._nid[2] | 0x10, self._nid[3],
                 self._nid[4], self._nid[5], "", title[:63], message[:255], 0)
            )
        except:
            pass

    def hide(self):
        """隐藏托盘图标"""
        self._running = False
        import win32gui
        try:
            if self._nid:
                win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, self._nid)
        except:
            pass
        try:
            if self._hwnd:
                win32gui.DestroyWindow(self._hwnd)
        except:
            pass
        logger.info("托盘图标已隐藏")

    def run_message_loop(self):
        """运行消息循环（阻塞）"""
        import win32gui
        import win32con

        while self._running:
            ret = win32gui.PumpWaitingMessages()
            if ret:
                break
            import time
            time.sleep(0.05)
