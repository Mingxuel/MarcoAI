# -*- coding: utf-8 -*-
"""
注册 marcoai:// 自定义协议，使网页双击打开也能触发本地 Python 命令。
运行一次即可（需以管理员权限，或用 /user 写入当前用户）。
用法:
    python AICode/MarcoAPI/register_protocol.py [--user]
"""
import os
import sys
import winreg

HANDLER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MarcoAI_Handler.py")


def _python_cmd():
    """返回调用 Handler 的命令：优先用 pythonw 避免黑窗口，否则用 python"""
    exe = sys.executable
    base, ext = os.path.splitext(exe)
    pyw = base + "w.exe" if ext.lower() == ".exe" else exe
    if os.path.isfile(pyw):
        return f'"{pyw}" "{HANDLER}" "%1"'
    return f'"{exe}" "{HANDLER}" "%1"'


def register(hive, key_path):
    """在指定根键下写入协议注册"""
    base_key = winreg.CreateKey(hive, key_path)
    winreg.SetValue(base_key, "", winreg.REG_SZ, "URL:MarcoAI Protocol")
    winreg.SetValueEx(base_key, "URL Protocol", 0, winreg.REG_SZ, "")
    winreg.CloseKey(base_key)

    shell = winreg.CreateKey(hive, key_path + r"\shell\open\command")
    winreg.SetValue(shell, "", winreg.REG_SZ, _python_cmd())
    winreg.CloseKey(shell)
    print("已注册协议:", key_path)


def main():
    use_user = "--user" in sys.argv
    hive = winreg.HKEY_CURRENT_USER if use_user else winreg.HKEY_CLASSES_ROOT
    key = r"Software\Classes\marcoai" if use_user else r"marcoai"
    print("Handler:", HANDLER)
    print("命令:", _python_cmd())
    try:
        register(hive, key)
    except PermissionError:
        print("无权限写入，请尝试使用 --user 参数（当前用户）或以管理员运行。")
        sys.exit(1)
    print("marcoai:// 协议注册成功！现在双击 HTML 即可使用快捷命令。")


if __name__ == "__main__":
    main()
