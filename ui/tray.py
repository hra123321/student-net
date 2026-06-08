"""
系统托盘模块
使用 Windows Shell_NotifyIconW API 实现系统托盘图标
"""
import ctypes
import ctypes.wintypes
import logging
import struct
import threading
import time

logger = logging.getLogger("CampusNet.Tray")

# WNDPROC 类型 - 用于 WNDCLASSW.lpfnWndProc
WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,      # LRESULT
    ctypes.c_void_p,    # HWND
    ctypes.c_uint32,    # UINT
    ctypes.c_void_p,    # WPARAM
    ctypes.c_void_p     # LPARAM
)

# Windows API 常量
WM_USER = 0x0400
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
NIF_SHOWTIP = 0x00000080

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIM_SETVERSION = 0x00000004

NOTIFYICON_VERSION = 0x00000004

# GUID 结构
class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_byte * 8),
    ]


# WNDCLASSW - Python 3.12+ 的 ctypes.wintypes 已移除该结构
class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
    ]


# NOTIFYICONDATAW 结构
class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("hWnd", ctypes.c_void_p),
        ("uID", ctypes.c_uint32),
        ("uFlags", ctypes.c_uint32),
        ("uCallbackMessage", ctypes.c_uint32),
        ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", ctypes.c_uint32),
        ("dwStateMask", ctypes.c_uint32),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", ctypes.c_uint32),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", ctypes.c_uint32),
        ("guidItem", GUID),
        ("hBalloonIcon", ctypes.c_void_p),
    ]


class SysTrayIcon:
    """系统托盘图标"""

    def __init__(self, tooltip: str = "校园网登录助手"):
        self._tooltip = tooltip
        self._hwnd = None
        self._icon_handle = None
        self._nid = None
        self._running = False
        self._menu_handlers = {}
        self._on_quit = None
        self._on_double_click = None

    def set_handlers(self, on_double_click=None, on_quit=None):
        self._on_double_click = on_double_click
        self._on_quit = on_quit

    def create_icon_from_data(self, icon_data: bytes):
        """从 ICO 文件数据创建 HICON"""
        try:
            # 使用 LoadImage from shell32
            import tempfile, os
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ico")
            tmp.write(icon_data)
            tmp.close()
            hicon = ctypes.windll.user32.LoadImageW(
                0, tmp, 1, 32, 32, 0x00000010
            )
            os.unlink(tmp.name)
            return hicon
        except Exception as e:
            logger.warning("加载图标失败: %s", e)
            return 0

    def _create_default_icon(self):
        """创建一个默认图标（简单的窗口句柄图标）"""
        try:
            return ctypes.windll.user32.LoadIconW(0, 32512)  # IDI_APPLICATION
        except Exception:
            return 0

    def _window_proc(self, hwnd, msg, wparam, lparam):
        """窗口消息处理"""
        if msg == WM_DESTROY:
            ctypes.windll.user32.PostQuitMessage(0)
            return 0

        if msg == self._callback_msg:
            if lparam == WM_LBUTTONDBLCLK:
                if self._on_double_click:
                    self._on_double_click()
            elif lparam == WM_RBUTTONDOWN:
                self._show_context_menu()
            elif lparam == WM_LBUTTONDOWN:
                pass

        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _register_window_class(self):
        """注册窗口类"""
        wc = WNDPROC(self._window_proc)

        class_name = "CampusNetTrayClass_" + str(id(self))

        wnd_class = WNDCLASSW()
        wnd_class.style = 0
        wnd_class.lpfnWndProc = wc
        wnd_class.cbClsExtra = 0
        wnd_class.cbWndExtra = 0
        hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
        wnd_class.hInstance = hInstance
        wnd_class.hIcon = 0
        wnd_class.hCursor = 0
        wnd_class.hbrBackground = 0
        wnd_class.lpszMenuName = None
        wnd_class.lpszClassName = class_name

        atom = ctypes.windll.user32.RegisterClassW(ctypes.byref(wnd_class))
        if atom == 0:
            err = ctypes.WinError()
            logger.error("RegisterClassW failed: %s", err)
            raise err
        return class_name, hInstance

    def show(self):
        """显示托盘图标"""
        class_name, hInstance = self._register_window_class()
        self._callback_msg = WM_USER + 100

        self._hwnd = ctypes.windll.user32.CreateWindowExW(
            0, class_name, "CampusNetTray", 0,
            0, 0, 0, 0, 0, 0, hInstance, None
        )

        if not self._hwnd:
            logger.error("创建窗口失败")
            return

        # 创建图标
        self._icon_handle = self._create_default_icon()

        # 初始化 NOTIFYICONDATA
        self._nid = NOTIFYICONDATAW()
        self._nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        self._nid.hWnd = self._hwnd
        self._nid.uID = 100
        self._nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        self._nid.uCallbackMessage = self._callback_msg
        self._nid.hIcon = self._icon_handle
        self._nid.szTip = self._tooltip[:127]
        self._nid.uVersion = NOTIFYICON_VERSION

        # 添加图标
        ret = ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid))
        if ret == 0:
            err = ctypes.windll.kernel32.GetLastError()
            logger.error("Shell_NotifyIconW failed: %d", err)
            ctypes.windll.user32.MessageBoxW(None, "托盘图标添加失败", "提示", 0)
            return
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(self._nid))
        self._running = True
        logger.info("托盘图标已显示")

    def _show_context_menu(self):
        """显示右键菜单"""
        # 使用简单的窗口菜单
        menu = ctypes.windll.user32.CreatePopupMenu()
        ctypes.windll.user32.InsertMenuW(menu, 0, 0x0000, 1, "显示面板")
        ctypes.windll.user32.InsertMenuW(menu, 1, 0x0000, 2, "立即重登")
        ctypes.windll.user32.InsertMenuW(menu, 2, 0x0000, 3, "一键优化")
        ctypes.windll.user32.InsertMenuW(menu, 3, 0x0400, 4, "退出")

        # 获取鼠标位置
        pos = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pos))

        # 设置前台窗口
        ctypes.windll.user32.SetForegroundWindow(self._hwnd)

        # 显示菜单
        cmd = ctypes.windll.user32.TrackPopupMenu(
            menu, 0x0100, pos.x, pos.y, 0, self._hwnd, None
        )

        ctypes.windll.user32.DestroyMenu(menu)
        self._handle_menu_command(cmd)

    def _handle_menu_command(self, cmd: int):
        """处理菜单命令"""
        if cmd == 1 and self._on_double_click:
            self._on_double_click()
        elif cmd == 2:
            # 立即重登 - 通过消息发送回主程序
            if hasattr(self, "_on_relogin") and self._on_relogin:
                self._on_relogin()
        elif cmd == 3:
            if hasattr(self, "_on_optimize") and self._on_optimize:
                self._on_optimize()
        elif cmd == 4:
            if self._on_quit:
                self._on_quit()
            self.hide()

    def set_relogin_handler(self, handler):
        self._on_relogin = handler

    def set_optimize_handler(self, handler):
        self._on_optimize = handler

    def show_balloon(self, title: str, message: str, timeout_ms: int = 3000):
        """显示气球提示"""
        if not self._nid:
            return
        self._nid.uFlags = NIF_INFO
        self._nid.szInfoTitle = title[:63]
        self._nid.szInfo = message[:255]
        self._nid.dwInfoFlags = 0x00000000  # NIIF_NONE
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))
        self._nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP

    def hide(self):
        """隐藏托盘图标"""
        self._running = False
        if self._nid:
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            self._nid = None
        if self._hwnd:
            ctypes.windll.user32.DestroyWindow(self._hwnd)
            self._hwnd = None
        logger.info("托盘图标已隐藏")

    def run_message_loop(self):
        """运行消息循环（阻塞）"""
        msg = ctypes.wintypes.MSG()
        while self._running:
            ret = ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0:  # WM_QUIT
                break
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.01)
