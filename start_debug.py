"""Interactive launcher with persistent diagnostics; does not cross desktops."""
import ctypes
from ctypes import wintypes
import logging
import os
from pathlib import Path
import runpy
import sys


def desktop_name():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    user32.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    desktop = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    name = ctypes.create_unicode_buffer(1024)
    needed = wintypes.DWORD()
    if not user32.GetUserObjectInformationW(
        desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return name.value


def main():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(root / "runtime.log", encoding="utf-8"),
        ],
        force=True,
    )
    try:
        desktop = desktop_name()
        logging.info("启动诊断：PID=%s，桌面=%s", os.getpid(), desktop)
        if desktop.lower().startswith("codexsandboxdesktop"):
            logging.error(
                "当前是隔离桌面，无法监听正常桌面的 QQ/微信。"
                "请在资源管理器中双击 Start.cmd；本次不注册热键。"
            )
            return 1
        logging.info("请保持此窗口打开；退出请按 Ctrl+C。日志：%s", root / "runtime.log")
        logging.info("默认在 QQ/微信输入框按 Enter 将生成并自动发送图片，请先在自己的聊天中测试。")
        runpy.run_path(str(root / "main.py"), run_name="__main__")
        return 0
    except KeyboardInterrupt:
        logging.info("已停止监听。")
        return 0
    except Exception:
        logging.exception("启动或运行失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
