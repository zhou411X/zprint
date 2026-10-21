#!/usr/bin/python3
"""Per-user installation; never overwrites another application's key binding."""

import argparse
import os
from pathlib import Path
import shlex
import shutil

from gi.repository import Gio, GLib

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
DEST = DATA / "zprint"
BIN = Path.home() / ".local/bin/zprint"
DESKTOP = DATA / "applications/io.github.zprint.Zprint.desktop"
ICON = DATA / "icons/hicolor/scalable/apps/zprint.svg"
EXTENSION_UUID = "zprint@zhou411X"
from zprint_app.shortcuts import BASE, CUSTOM_SCHEMA, install_shortcuts, shortcut_settings


def desktop_quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$") + '"'


def uninstall():
    extension = DATA / "gnome-shell/extensions" / EXTENSION_UUID
    if (extension / ".zprint-install").exists():
        shell = Gio.Settings.new("org.gnome.shell")
        shell.set_strv("enabled-extensions", [value for value in shell.get_strv("enabled-extensions")
                                               if value != EXTENSION_UUID])
        Gio.Settings.sync()
        shutil.rmtree(extension)
    settings = shortcut_settings()
    if settings:
        paths = list(settings.get_strv("custom-keybindings"))
        for suffix in ("capture", "clipboard"):
            path = BASE + "zprint-" + suffix + "/"
            item = Gio.Settings.new_with_path(CUSTOM_SCHEMA, path)
            expected = f"{shlex.quote(str(BIN))} --{suffix}"
            if path in paths and item.get_string("command") == expected:
                paths.remove(path)
                for key in ("name", "command", "binding"):
                    item.reset(key)
        settings.set_strv("custom-keybindings", paths)
        Gio.Settings.sync()
    for path in (BIN, DESKTOP, ICON):
        if path.exists():
            path.unlink()
    if (DEST / ".zprint-install").exists():
        shutil.rmtree(DEST)
    print("已移除 zprint 的用户安装；源码和导出的图片保留。")


def main():
    parser = argparse.ArgumentParser(description="安装 zprint 到当前用户，无需 sudo")
    parser.add_argument("--no-shortcuts", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--enable-shell-extension", action="store_true",
                        help="安装并启用 GNOME 46 原选区浮动工具栏；首次安装需要重新登录")
    args = parser.parse_args()
    if args.uninstall:
        uninstall()
        return
    if DEST.exists() and not (DEST / ".zprint-install").exists():
        raise SystemExit(f"拒绝覆盖未知目录：{DEST}")
    if BIN.exists() and "# zprint launcher" not in BIN.read_text():
        raise SystemExit(f"拒绝覆盖已有命令：{BIN}")
    extension = DATA / "gnome-shell/extensions" / EXTENSION_UUID
    install_extension = args.enable_shell_extension or (extension / ".zprint-install").exists()
    if install_extension and extension.exists() and not (extension / ".zprint-install").exists():
        raise SystemExit(f"拒绝覆盖未知扩展目录：{extension}")
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / ".zprint-install").write_text("zprint\n")
    shutil.copytree(ROOT / "zprint_app", DEST / "zprint_app", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "zprint", DEST / "zprint")
    for path in (BIN, DESKTOP, ICON):
        path.parent.mkdir(parents=True, exist_ok=True)
    BIN.write_text("#!/bin/sh\n# zprint launcher\nexec /usr/bin/python3 " + shlex.quote(str(DEST / "zprint")) + ' "$@"\n')
    BIN.chmod(0o755)
    shutil.copy2(ROOT / "assets/zprint.svg", ICON)
    DESKTOP.write_text("\n".join([
        "[Desktop Entry]", "Type=Application", "Name=zprint", "GenericName=截图标记",
        "Comment=使用系统截图，轻松标记和分享", f"Exec={desktop_quote(BIN)} %F", "Icon=zprint",
        "Terminal=false", "Categories=Graphics;2DGraphics;", "StartupNotify=true",
        "StartupWMClass=io.github.zprint.Zprint", "MimeType=image/png;image/jpeg;image/webp;image/bmp;",
        "Actions=Capture;Clipboard;", "", "[Desktop Action Capture]", "Name=系统截图",
        f"Exec={desktop_quote(BIN)} --capture", "", "[Desktop Action Clipboard]", "Name=从剪贴板标记",
        f"Exec={desktop_quote(BIN)} --clipboard", "",
    ]))
    if not args.no_shortcuts:
        install_shortcuts(shlex.quote(str(BIN)))
    if install_extension:
        shutil.copytree(ROOT / "gnome-extension", extension, dirs_exist_ok=True)
        (extension / ".zprint-install").write_text("zprint\n")
    if args.enable_shell_extension:
        shell = Gio.Settings.new("org.gnome.shell")
        enabled = list(shell.get_strv("enabled-extensions"))
        if EXTENSION_UUID not in enabled:
            shell.set_strv("enabled-extensions", enabled + [EXTENSION_UUID])
        shell.set_boolean("disable-user-extensions", False)
        Gio.Settings.sync()
        print("已安装并配置启用 GNOME 46 浮动工具栏。首次安装或更新扩展后，请注销并重新登录桌面。")
    print(f"安装完成：{BIN}\n可以从应用菜单启动 zprint。源码修改后重新运行 install.sh 更新。")


if __name__ == "__main__":
    main()
