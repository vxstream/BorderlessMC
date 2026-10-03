#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BorderlessMC 1.0
================
Ищет уже запущенный процесс Minecraft (javaw.exe / java.exe) и превращает его
окно в borderless fullscreen: без рамки, без заголовка, на весь экран
(по умолчанию — монитор, на котором окно находится).

Зависимостей нет: только стандартная библиотека (ctypes + tkinter).
Собирается в один .exe через PyInstaller.

Запуск:
    python borderless_mc.py            # GUI
    python borderless_mc.py --list     # показать найденные окна и выйти
    python borderless_mc.py --pid 1234 # сразу применить к процессу
    python borderless_mc.py --restore  # восстановить все окна и выйти

Hotkey: F11 — переключить бордерлесс/восстановить (после выбора окна).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import threading
import time
from ctypes import wintypes

# --------------------------------------------------------------------------- #
#  Win32 API                                                                  #
# --------------------------------------------------------------------------- #

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
except OSError:  # pragma: no cover - DWM есть везде на Win7+
    dwmapi = None

IS_64BIT = ctypes.sizeof(ctypes.c_void_p) == 8

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

GWL_STYLE = -16
GWL_EXSTYLE = -20

WS_POPUP = 0x80000000
WS_OVERLAPPED = 0x00000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
WS_BORDER = 0x00800000
WS_DLGFRAME = 0x00400000
WS_CLIPSIBLINGS = 0x04000000
WS_CLIPCHILDREN = 0x02000000
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080

SW_HIDE = 0
SW_SHOW = 5
SW_SHOWNA = 8
SW_RESTORE = 9
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040

MONITOR_DEFAULTTONEAREST = 0x00000002
MONITORINFOF_PRIMARY = 0x00000001

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_DESTROY = 0x0002
WM_QUIT = 0x0012
HOTKEY_ID = 0xB01D

MC_PROCESS_NAMES = ("javaw.exe", "java.exe")
MC_TITLE_HINTS = (
    "minecraft",
    "java",
    "lwjgl",
    "openal",
    "mojang",
    "net.minecraft",
)

# SetWindowLongPtrW есть только в 64-битном user32; в 32-битном — SetWindowLongW.
_SET_WINDOW_LONG = (
    user32.SetWindowLongPtrW if IS_64BIT else user32.SetWindowLongW
)
_SET_WINDOW_LONG.restype = ctypes.c_long
_SET_WINDOW_LONG.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]

user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]

user32.SetWindowPos.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]

user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.IsZoomed.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]

user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]

kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

user32.RegisterClassW.restype = wintypes.ATOM
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.DestroyWindow.argtypes = [wintypes.HWND]

if dwmapi is not None:
    class MARGINS(ctypes.Structure):
        _fields_ = [
            ("cxLeftWidth", ctypes.c_long),
            ("cxRightWidth", ctypes.c_long),
            ("cyTopHeight", ctypes.c_long),
            ("cyBottomHeight", ctypes.c_long),
        ]

    dwmapi.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
    dwmapi.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(MARGINS)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]


def get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_style(hwnd: int) -> int:
    return user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF


def get_exstyle(hwnd: int) -> int:
    return user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF


def set_style(hwnd: int, style: int, exstyle: int) -> None:
    _SET_WINDOW_LONG(hwnd, GWL_STYLE, style)
    _SET_WINDOW_LONG(hwnd, GWL_EXSTYLE, exstyle)


# --------------------------------------------------------------------------- #
#  Поиск процессов и окон                                                    #
# --------------------------------------------------------------------------- #

def java_processes() -> dict[int, str]:
    """{pid: полный путь к exe} для всех javaw.exe / java.exe."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())

    found: dict[int, str] = {}
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.lower()
            if name in MC_PROCESS_NAMES:
                found[entry.th32ProcessID] = name
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return found


def top_level_windows() -> list[int]:
    handles: list[int] = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    def callback(hwnd, _lparam):
        handles.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return handles


def _looks_like_minecraft(hwnd: int, exe_name: str, title: str) -> bool:
    if exe_name not in MC_PROCESS_NAMES:
        return False
    if not user32.IsWindowVisible(hwnd):
        return False
    cls = get_class_name(hwnd).lower()
    if cls in ("progman", "workerw", "shell_traywnd", "windowssearchbox"):
        return False
    if not title.strip():
        # Окно без заголовка у Minecraft — это обычно и есть окно игры (GLFW).
        return cls.startswith(("glfw", "lwjgl"))
    low = title.lower()
    return any(hint in low for hint in MC_TITLE_HINTS) or cls.startswith(
        ("glfw", "lwjgl")
    )


def find_minecraft_windows() -> list[dict]:
    """Список окон Minecraft: [{'hwnd','pid','title','exe','monitor'}]."""
    procs = java_processes()
    result: list[dict] = []
    if not procs:
        return result

    for hwnd in top_level_windows():
        pid = get_window_pid(hwnd)
        exe = procs.get(pid)
        if exe is None:
            continue
        title = get_window_text(hwnd)
        if not _looks_like_minecraft(hwnd, exe, title):
            continue
        result.append(
            {
                "hwnd": hwnd,
                "pid": pid,
                "title": title or "(без заголовка)",
                "exe": exe,
                "monitor": monitor_index_for(hwnd),
            }
        )
    return result


def monitor_info(hwnd: int) -> MONITORINFO | None:
    hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not hmon:
        return None
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
        return None
    return info


def enumerate_monitors() -> list[MONITORINFO]:
    """Все мониторы в порядке EnumDisplayMonitors (0 — основной)."""
    found: list[MONITORINFO] = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.c_void_p
    )

    def cb(hmon, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            found.append(info)
        return True

    user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(cb), 0)
    return found


def monitor_index_for(hwnd: int) -> int:
    """Индекс монитора, на котором лежит окно (0 = основной)."""
    info = monitor_info(hwnd)
    if info is None:
        return 0
    if info.dwFlags & MONITORINFOF_PRIMARY:
        return 0
    for index, mon in enumerate(enumerate_monitors()):
        if (mon.rcMonitor.left == info.rcMonitor.left
                and mon.rcMonitor.top == info.rcMonitor.top):
            return index
    return 0


# --------------------------------------------------------------------------- #
#  Ядро: бордерлесс                                                           #
# --------------------------------------------------------------------------- #

class WindowStateStore:
    """Сохраняет оригинальные стили/размеры, чтобы восстановить окно потом."""

    def __init__(self, path: str | None = None):
        self.path = path
        self.data: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if self.path and os.path.isfile(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    self.data = json.load(fh)
            except (OSError, ValueError):
                self.data = {}

    def save(self) -> None:
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=1)
        except OSError:
            pass

    def remember(self, hwnd: int, style: int, exstyle: int, rect: tuple[int, ...]) -> None:
        self.data[str(hwnd)] = {
            "style": style,
            "exstyle": exstyle,
            "rect": list(rect),
            "ts": int(time.time()),
        }

    def recall(self, hwnd: int) -> dict | None:
        return self.data.get(str(hwnd))


def make_borderless(hwnd: int, monitor: int = -1, store: WindowStateStore | None = None) -> str:
    """Делает окно бордерлесс-фуллскрином. Возвращает описание результата."""
    if not user32.IsWindow(hwnd):
        raise RuntimeError("Окно больше не существует.")

    info = monitor_info(hwnd)
    if info is None:
        raise RuntimeError("Не удалось определить монитор окна.")
    if monitor is not None and monitor >= 0:
        info = _select_monitor(monitor)
        if info is None:
            raise RuntimeError(f"Монитор #{monitor} не найден.")

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    if store is not None:
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        store.remember(
            hwnd, get_style(hwnd), get_exstyle(hwnd),
            (rect.left, rect.top, rect.right, rect.bottom),
        )

    style = get_style(hwnd)
    exstyle = get_exstyle(hwnd)

    # Убираем всё, что рисует рамку, и превращаем окно в popup.
    style &= ~(WS_CAPTION | WS_THICKFRAME | WS_BORDER | WS_DLGFRAME
               | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
    style |= WS_POPUP | WS_CLIPCHILDREN | WS_CLIPSIBLINGS
    exstyle &= ~(WS_EX_APPWINDOW | WS_EX_TOOLWINDOW)
    set_style(hwnd, style, exstyle)

    if dwmapi is not None:
        margins = MARGINS(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))

    m = info.rcMonitor
    flags = SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOACTIVATE
    user32.SetWindowPos(hwnd, 0, m.left, m.top,
                        m.right - m.left, m.bottom - m.top, flags)
    user32.SetWindowPos(hwnd, 0, m.left, m.top, 0, 0,
                        flags | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
    user32.ShowWindow(hwnd, SW_SHOWNA)
    user32.BringWindowToTop(hwnd)
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass

    if store is not None:
        store.save()

    return "%dx%d @ (%d, %d)" % (m.right - m.left, m.bottom - m.top, m.left, m.top)


def restore_window(hwnd: int, store: WindowStateStore | None = None) -> str:
    if not user32.IsWindow(hwnd):
        raise RuntimeError("Окно больше не существует.")
    saved = store.recall(hwnd) if store else None
    if not saved:
        # Восстанавливаем «по умолчанию», если нет сохранённого состояния.
        style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_THICKFRAME
        style |= WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_CLIPCHILDREN | WS_CLIPSIBLINGS
        set_style(hwnd, style, WS_EX_APPWINDOW)
        rect = None
    else:
        set_style(hwnd, saved["style"], saved["exstyle"])
        rect = saved.get("rect")

    if dwmapi is not None:
        margins = MARGINS(0, 0, 0, 0)
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))

    if rect:
        user32.SetWindowPos(hwnd, 0, rect[0], rect[1],
                            rect[2] - rect[0], rect[3] - rect[1],
                            SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    else:
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                            | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    user32.ShowWindow(hwnd, SW_RESTORE)
    if store is not None:
        store.data.pop(str(hwnd), None)
        store.save()
    return "восстановлено"


def _select_monitor(index: int) -> MONITORINFO | None:
    monitors = enumerate_monitors()
    return monitors[index] if 0 <= index < len(monitors) else None


def monitor_count() -> int:
    return len(enumerate_monitors())


# --------------------------------------------------------------------------- #
#  Hotkey F11 (отдельный поток со своим message loop)                          #
# --------------------------------------------------------------------------- #

class HotkeyListener:
    """Регистрирует F11 и зовёт колбэк из отдельного потока."""

    def __init__(self, callback, keys=(0x7A,)):  # 0x7A = VK_F11
        self.callback = callback
        self.vk = keys[0]
        self.thread: threading.Thread | None = None
        self.hwnd = None
        self._ready = threading.Event()
        self._ok = False

    def start(self) -> bool:
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self._ready.wait(timeout=2.0)
        return self._ok

    def _run(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        global _WNDPROC_KEEPALIVE
        if _WNDPROC_KEEPALIVE is None:
            _WNDPROC_KEEPALIVE = WNDPROC(_wnd_proc)
        wndclass = WNDCLASSW()
        wndclass.style = 0x0003  # CS_HREDRAW | CS_VREDRAW
        wndclass.lpfnWndProc = _WNDPROC_KEEPALIVE
        wndclass.hInstance = hinstance
        wndclass.lpszClassName = "BorderlessMC_Hotkey"
        if not user32.RegisterClassW(ctypes.byref(wndclass)):
            # Класс мог остаться от прошнего запуска — это не ошибка.
            pass
        hwnd = user32.CreateWindowExW(
            0, "BorderlessMC_Hotkey", "BorderlessMC", 0,
            0, 0, 0, 0, None, None, hinstance, None,
        )
        if not hwnd:
            self._ready.set()
            return
        self.hwnd = hwnd
        self._ok = bool(
            user32.RegisterHotKey(hwnd, HOTKEY_ID, MOD_NOREPEAT, self.vk)
        )
        self._ready.set()

        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                try:
                    self.callback()
                except Exception:
                    pass
            if msg.message == WM_QUIT:
                break

    def stop(self) -> None:
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)
WNDENUMPROC_T = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


# Держим ссылку на CFUNCTYPE, иначе Python соберёт его до конца потока
# и вызов wndproc внутри RegisterClassW упадёт.
_WNDPROC_KEEPALIVE = None


def _wnd_proc(hwnd, msg, wparam, lparam):
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


user32.GetClassNameW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.EnumWindows.argtypes = [WNDENUMPROC_T, wintypes.LPARAM]
user32.EnumDisplayMonitors.restype = wintypes.BOOL
user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


# --------------------------------------------------------------------------- #
#  GUI                                                                        #
# --------------------------------------------------------------------------- #

def state_file_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "BorderlessMC", "state.json")


def run_gui() -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    store = WindowStateStore(state_file_path())

    root = tk.Tk()
    root.title("BorderlessMC")
    root.geometry("640x430")
    root.minsize(560, 380)
    root.configure(bg="#1e1e22")

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("Dark.TFrame", background="#1e1e22")
    style.configure("Dark.TLabel", background="#1e1e22", foreground="#d6d6d6")
    style.configure(
        "Dark.Treeview", background="#2b2b31", fieldbackground="#2b2b31",
        foreground="#e6e6e6", borderwidth=0,
    )
    style.configure(
        "Dark.Treeview.Heading", background="#3a3a42", foreground="#ffffff"
    )
    style.map("Dark.Treeview", background=[("selected", "#4a7ab5")])

    header = ttk.Frame(root, style="Dark.TFrame")
    header.pack(fill="x", padx=14, pady=(14, 6))
    ttk.Label(
        header, text="BorderlessMC", style="Dark.TLabel",
        font=("Segoe UI", 15, "bold"),
    ).pack(side="left")
    ttk.Label(
        header, text=f"  → {monitor_count()} монитор(ов)",
        style="Dark.TLabel", font=("Segoe UI", 9),
    ).pack(side="left")

    toolbar = ttk.Frame(root, style="Dark.TFrame")
    toolbar.pack(fill="x", padx=14)

    btn_refresh = ttk.Button(toolbar, text="Обновить (F5)", command=lambda: refresh())
    btn_refresh.pack(side="left")

    monitor_var = tk.IntVar(value=-1)
    ttk.Label(toolbar, text="  Монитор:", style="Dark.TLabel").pack(side="left")
    monitor_box = ttk.Spinbox(toolbar, from_=-1, to=99, width=4,
                              textvariable=monitor_var,
                              command=lambda: status.set(
                                  "−1 = монитор окна, 0 = основной" if monitor_var.get() == -1
                                  else f"Монитор #{monitor_var.get()}"))
    monitor_box.pack(side="left")

    ttk.Label(
        toolbar, text="  (−1 = где окно, 0 = основной)",
        style="Dark.TLabel", font=("Segoe UI", 8),
    ).pack(side="left")

    body = ttk.Frame(root, style="Dark.TFrame")
    body.pack(fill="both", expand=True, padx=14, pady=10)

    columns = ("pid", "title", "exe", "monitor", "state")
    tree = ttk.Treeview(body, columns=columns, show="headings", style="Dark.Treeview",
                        selectmode="browse")
    tree.heading("pid", text="PID")
    tree.heading("title", text="Окно")
    tree.heading("exe", text="Процесс")
    tree.heading("monitor", text="Экран")
    tree.heading("state", text="Состояние")
    tree.column("pid", width=70, anchor="center", stretch=False)
    tree.column("title", width=300)
    tree.column("exe", width=90, anchor="center", stretch=False)
    tree.column("monitor", width=60, anchor="center", stretch=False)
    tree.column("state", width=110, anchor="center", stretch=False)
    scroll = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    actions = ttk.Frame(root, style="Dark.TFrame")
    actions.pack(fill="x", padx=14, pady=(0, 8))
    ttk.Button(actions, text="◼  Бордерлесс фуллскрин",
               command=lambda: apply_to_selection()).pack(side="left")
    ttk.Button(actions, text="▣  Восстановить",
               command=lambda: restore_selection()).pack(side="left", padx=8)
    ttk.Button(actions, text="Восстановить все",
               command=lambda: restore_all()).pack(side="left")

    status = tk.StringVar(value="Запусти Minecraft и нажми «Обновить».")
    ttk.Label(
        root, textvariable=status, style="Dark.TLabel",
        font=("Segoe UI", 9), anchor="w",
    ).pack(fill="x", padx=14, pady=(0, 12))

    current: dict[int, dict] = {}

    def refresh() -> None:
        tree.delete(*tree.get_children())
        current.clear()
        try:
            windows = find_minecraft_windows()
        except Exception as exc:  # noqa: BLE001
            status.set(f"Ошибка поиска: {exc}")
            return
        for win in windows:
            saved = store.recall(win["hwnd"])
            state = "бордерлесс" if saved else "обычное"
            tree.insert(
                "", "end", iid=str(win["hwnd"]),
                values=(win["pid"], win["title"], win["exe"],
                        win["monitor"], state),
            )
            current[win["hwnd"]] = win
        if not windows:
            status.set("Minecraft не найден. Запусти игру и нажми F5.")
        else:
            status.set(f"Найдено окон: {len(windows)}. Выбери окно и нажми «Бордерлесс».")
            kids = tree.get_children()
            if kids:
                tree.selection_set(kids[0])

    def selected_hwnd() -> int | None:
        sel = tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def apply_to_selection() -> None:
        hwnd = selected_hwnd()
        if hwnd is None:
            messagebox.showinfo("BorderlessMC", "Сначала выбери окно в списке.")
            return
        try:
            geom = make_borderless(hwnd, monitor_var.get(), store)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("BorderlessMC", str(exc))
            return
        status.set(f"Готово: бордерлесс фуллскрин {geom}. F11 — вернуть окно.")
        refresh()

    def restore_selection() -> None:
        hwnd = selected_hwnd()
        if hwnd is None:
            messagebox.showinfo("BorderlessMC", "Сначала выбери окно в списке.")
            return
        try:
            restore_window(hwnd, store)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("BorderlessMC", str(exc))
            return
        status.set("Окно восстановлено.")
        refresh()

    def restore_all() -> None:
        count = 0
        for hwnd in list(current):
            try:
                restore_window(hwnd, store)
                count += 1
            except Exception:  # noqa: BLE001
                continue
        status.set(f"Восстановлено окон: {count}")
        refresh()

    def toggle_hotkey() -> None:
        hwnd = selected_hwnd()
        if hwnd is None:
            hwnds = list(current)
            if not hwnds:
                return
            hwnd = hwnds[0]
        try:
            if store.recall(hwnd):
                restore_window(hwnd, store)
                status.set("F11: окно восстановлено.")
            else:
                make_borderless(hwnd, -1, store)
                status.set("F11: бордерлесс фуллскрин включён.")
        except Exception:  # noqa: BLE001
            pass

    hotkey = HotkeyListener(toggle_hotkey)
    hotkey_ok = hotkey.start()

    root.bind("<F5>", lambda _e: refresh())
    root.bind("<Return>", lambda _e: apply_to_selection())
    root.protocol("WM_DELETE_WINDOW", root.destroy)

    refresh()
    if not hotkey_ok:
        status.set(
            "Горячая клавиша F11 недоступна (окно не в фокусе) — используй кнопки."
        )
    root.mainloop()
    hotkey.stop()
    return 0


# --------------------------------------------------------------------------- #
#  CLI                                                                        #
# --------------------------------------------------------------------------- #

def run_cli(args: argparse.Namespace) -> int:
    store = WindowStateStore(state_file_path())

    if args.restore:
        n = 0
        for hwnd in list(store.data):
            try:
                restore_window(int(hwnd), store)
                n += 1
            except Exception:  # noqa: BLE001
                continue
        print(f"Восстановлено окон: {n}")
        return 0

    if args.list:
        windows = find_minecraft_windows()
        if not windows:
            print("Minecraft не найден.")
            return 1
        for win in windows:
            print(f"hwnd={win['hwnd']:<10} pid={win['pid']:<8} "
                  f"screen={win['monitor']}  {win['exe']}  {win['title']}")
        return 0

    if args.pid:
        targets = [w for w in find_minecraft_windows() if w["pid"] == args.pid]
        if not targets:
            print(f"У процесса {args.pid} нет подходящего окна.")
            return 1
        for win in targets:
            print(f"pid={win['pid']}: {make_borderless(win['hwnd'], args.monitor, store)}")
        return 0

    return run_gui()


def _ensure_stdio() -> None:
    """Приводит stdout/stderr к utf-8, иначе русский текст роняет вывод.

    В .exe, собранном PyInstaller с --windowed, бывают два варианта:
      * sys.stdout равен None — тогда подставляем поток в devnull;
      * поток есть, но с системной кодировкой (cp1252/cp866) — тогда
        русский текст в --help падает с UnicodeEncodeError.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
                continue
            except (ValueError, OSError):
                pass
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            import io

            setattr(
                sys, name,
                io.TextIOWrapper(buffer, encoding="utf-8", errors="replace",
                                 line_buffering=True),
            )


def main(argv: list[str] | None = None) -> int:
    _ensure_stdio()

    if os.name != "nt":
        print("BorderlessMC работает только под Windows.", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(
        prog="BorderlessMC",
        description="Делает окно Minecraft (javaw.exe) бордерлесс фуллскрином.",
    )
    parser.add_argument("--list", action="store_true", help="показать окна и выйти")
    parser.add_argument("--pid", type=int, help="применить к процессу с этим PID")
    parser.add_argument("--monitor", type=int, default=-1,
                        help="индекс монитора, −1 (по умолчанию) = монитор окна")
    parser.add_argument("--restore", action="store_true",
                        help="восстановить все сохранённые окна и выйти")
    parser.add_argument("--selftest", action="store_true",
                        help="проверить привязки Win32 и выйти с кодом 0")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    return run_cli(args)


def selftest() -> int:
    """Проверяет, что все ctypes-привязки разрешились. Код 0 — успех."""
    checks = [
        ("GetWindowLongW", lambda: user32.GetWindowLongW),
        ("SetWindowLongPtrW", lambda: _SET_WINDOW_LONG),
        ("SetWindowPos", lambda: user32.SetWindowPos),
        ("GetWindowRect", lambda: user32.GetWindowRect),
        ("GetMonitorInfoW", lambda: user32.GetMonitorInfoW),
        ("EnumWindows", lambda: user32.EnumWindows),
        ("EnumDisplayMonitors", lambda: user32.EnumDisplayMonitors),
        ("CreateToolhelp32Snapshot", lambda: kernel32.CreateToolhelp32Snapshot),
        ("Process32FirstW", lambda: kernel32.Process32FirstW),
        ("RegisterHotKey", lambda: user32.RegisterHotKey),
        ("DwmExtendFrameIntoClientArea",
         lambda: dwmapi.DwmExtendFrameIntoClientArea if dwmapi else None),
    ]
    failed = [name for name, get in checks if get() is None]

    if failed:
        print("НЕ РАЗРЕШИЛИСЬ:", ", ".join(failed))
        return 1

    monitors = monitor_count()
    print("Win32 OK | разрядность:",
          "64-bit" if IS_64BIT else "32-bit",
          "| мониторов:", monitors)

    # Размеры структур должны совпадать с ожидаемыми для Win32/Win64.
    if ctypes.sizeof(PROCESSENTRY32W) != 556:
        print("Неверный размер PROCESSENTRY32W:",
              ctypes.sizeof(PROCESSENTRY32W))
        return 1
    if ctypes.sizeof(MONITORINFO) != 40:
        print("Неверный размер MONITORINFO:", ctypes.sizeof(MONITORINFO))
        return 1

    try:
        procs = java_processes()
        print("Процессов java/javaw:", len(procs))
    except OSError as exc:
        print("Снимок процессов не удался:", exc)
        return 1

    print("SELFTEST OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())