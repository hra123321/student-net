"""
系统托盘模块
使用 win32gui 实现系统托盘图标（比手写 ctypes 更可靠）
"""
import logging
import threading
import win32api
import win32con
import win32gui

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
        self._on_restore = None
        self._msg_id = win32con.WM_USER + 100
        self._show_message = win32con.WM_USER + 101
        self._class_name = None

    def set_handlers(self, on_double_click=None, on_quit=None):
        self._on_double_click = on_double_click
        self._on_quit = on_quit

    def set_relogin_handler(self, handler):
        self._on_relogin = handler

    def set_optimize_handler(self, handler):
        self._on_optimize = handler

    def set_restore_handler(self, handler):
        self._on_restore = handler

    def _window_proc(self, hwnd, msg, wparam, lparam):
        """窗口消息处理"""
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0

        if msg == self._msg_id:
            if lparam == win32con.WM_LBUTTONDBLCLK:
                if self._on_double_click:
                    self._on_double_click()
            elif lparam in (win32con.WM_RBUTTONUP, win32con.WM_CONTEXTMENU):
                self._show_context_menu()
            return 0

        if msg == self._show_message:
            if self._on_double_click:
                self._on_double_click()
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _on_destroy(self, hwnd, msg, wparam, lparam):
        """处理托盘隐藏窗口销毁。"""
        win32gui.PostQuitMessage(0)
        return 0

    def _on_tray_notify(self, hwnd, msg, wparam, lparam):
        """处理系统托盘点击消息。"""
        logger.debug("托盘消息: lparam=%s", lparam)
        return self._window_proc(hwnd, msg, wparam, lparam)

    def _show_context_menu(self):
        """显示右键菜单"""
        menu = None
        try:
            menu = win32gui.CreatePopupMenu()
            win32gui.AppendMenu(menu, win32con.MF_STRING, 1, "显示面板")
            win32gui.AppendMenu(menu, win32con.MF_STRING, 2, "立即重登")
            win32gui.AppendMenu(menu, win32con.MF_STRING, 3, "一键优化")
            win32gui.AppendMenu(menu, win32con.MF_STRING, 4, "一键还原")
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
            win32gui.AppendMenu(menu, win32con.MF_STRING, 5, "退出")

            pos = win32gui.GetCursorPos()
            try:
                win32gui.SetForegroundWindow(self._hwnd)
            except Exception:
                pass
            cmd = win32gui.TrackPopupMenu(
                menu,
                win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON | win32con.TPM_RETURNCMD,
                pos[0],
                pos[1],
                0,
                self._hwnd,
                None,
            )
            win32gui.PostMessage(self._hwnd, win32con.WM_NULL, 0, 0)
            self._handle_menu_command(cmd)
        except Exception as e:
            logger.error("显示托盘菜单失败: %s", e)
        finally:
            if menu:
                try:
                    win32gui.DestroyMenu(menu)
                except Exception:
                    pass

    def _handle_menu_command(self, cmd: int):
        """处理菜单命令"""
        if cmd == 1 and self._on_double_click:
            self._on_double_click()
        elif cmd == 2 and self._on_relogin:
            self._on_relogin()
        elif cmd == 3 and self._on_optimize:
            threading.Thread(target=self._on_optimize, daemon=True).start()
        elif cmd == 4 and self._on_restore:
            threading.Thread(target=self._on_restore, daemon=True).start()
        elif cmd == 5:
            if self._on_quit:
                self._on_quit()
            self.hide()

    def show(self):
        """显示托盘图标"""
        # 创建隐藏窗口
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = {
            win32con.WM_DESTROY: self._on_destroy,
            self._msg_id: self._on_tray_notify,
            self._show_message: self._window_proc,
        }
        wc.lpszClassName = "CampusNetTrayWindow"
        self._class_name = wc.lpszClassName
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.hCursor = 0
        wc.hbrBackground = 0

        try:
            win32gui.RegisterClass(wc)
        except:
            pass

        self._hwnd = win32gui.CreateWindow(
            wc.lpszClassName, "Tray", win32con.WS_OVERLAPPED,
            0, 0, 0, 0, 0, 0, wc.hInstance, None
        )

        if not self._hwnd:
            logger.error("CreateWindow failed")
            return

        # 托盘图标参数
        hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

        flags = win32gui.NIF_MESSAGE | win32gui.NIF_ICON | win32gui.NIF_TIP

        self._nid = (self._hwnd, 100, flags, self._msg_id, hicon, self._tooltip[:127], "")

        # 添加托盘图标
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self._nid)
        except Exception as e:
            logger.error("Shell_NotifyIcon failed: %s", e)
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "系统托盘图标创建失败", "提示", 0)
            return

        self._running = True
        logger.info("托盘图标已显示")

    def show_balloon(self, title: str, message: str, timeout_ms: int = 3000):
        """显示气球提示"""
        if not self._running:
            return
        try:
            # Pywin32 NOTIFYICONDATA order:
            # hwnd, id, flags, callback, icon, tip, info, timeout, infoTitle, infoFlags
            nid_balloon = (self._nid[0], self._nid[1],
                           self._nid[2] | 0x10,
                           0, self._nid[4], self._nid[5],
                           message[:255], timeout_ms, title[:63], 0)
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, nid_balloon)
        except Exception as e:
            logger.debug("Balloon failed: %s", e)

    def hide(self):
        """隐藏托盘图标"""
        self._running = False
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
        try:
            if self._class_name:
                win32gui.UnregisterClass(self._class_name, win32api.GetModuleHandle(None))
        except:
            pass
        logger.info("托盘图标已隐藏")

    def run_message_loop(self, idle_callback=None):
        """运行消息循环（阻塞）"""
        import time
        while self._running:
            ret = win32gui.PumpWaitingMessages()
            if ret:
                break
            if idle_callback:
                try:
                    idle_callback()
                except Exception as e:
                    logger.debug("托盘空闲回调异常: %s", e)
            time.sleep(0.05)
