"""Shortcut preferences and application information."""

from pathlib import Path
import shlex

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

from . import __version__
from .shortcuts import SHORTCUTS, normalize_binding, read_bindings, save_bindings, shortcut_label, shortcut_settings


def launcher_path():
    if Path(__file__).resolve().parent.parent == Path("/usr/lib/zprint"):
        return Path("/usr/bin/zprint")
    return Path.home() / ".local/bin/zprint"


def launcher_command():
    return shlex.quote(str(launcher_path()))


class ShortcutRecorder(Gtk.Dialog):
    def __init__(self, parent):
        super().__init__(title="录入快捷键", transient_for=parent, modal=True)
        self.binding = None
        self.set_default_size(430, 160)
        self.add_button("取消", Gtk.ResponseType.CANCEL)
        content = self.get_content_area()
        content.set_border_width(20)
        content.set_spacing(12)
        content.add(Gtk.Label(label="请按下新的组合键"))
        self.hint = Gtk.Label(label="例如 Ctrl + Alt + S；按 Esc 取消", wrap=True)
        self.hint.get_style_context().add_class("muted")
        content.add(self.hint)
        self.connect("key-press-event", self.key_pressed)
        self.show_all()

    def key_pressed(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.response(Gtk.ResponseType.CANCEL)
            return True
        if event.is_modifier:
            return True
        mods = event.state & Gtk.accelerator_get_default_mod_mask()
        try:
            self.binding = normalize_binding(Gtk.accelerator_name(event.keyval, mods))
        except ValueError as error:
            self.hint.set_text(str(error))
        else:
            self.response(Gtk.ResponseType.OK)
        return True


class Preferences(Gtk.Dialog):
    def __init__(self, parent, page="shortcuts"):
        super().__init__(title="设置", transient_for=parent, modal=True)
        self.set_default_size(520, 350)
        self.set_resizable(False)
        self.command = launcher_command()
        self.bindings = read_bindings(self.command)
        self.buttons = {}
        self.add_button("关闭", Gtk.ResponseType.CLOSE)
        content = self.get_content_area()
        content.set_border_width(16)
        notebook = Gtk.Notebook()
        content.add(notebook)
        shortcuts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin=20)
        hint = Gtk.Label(label="点击组合键进行修改，保存后立即生效。", xalign=0)
        hint.get_style_context().add_class("muted")
        shortcuts.pack_start(hint, False, False, 0)
        for action, title, _ in SHORTCUTS:
            row = Gtk.Box(spacing=10)
            row.pack_start(Gtk.Label(label=title, xalign=0), True, True, 0)
            key = Gtk.Button(label=shortcut_label(self.bindings[action]))
            key.set_size_request(170, -1)
            key.connect("clicked", lambda _, value=action: self.record(value))
            self.buttons[action] = key
            row.pack_start(key, False, False, 0)
            clear = Gtk.Button(label="停用")
            clear.connect("clicked", lambda _, value=action: self.set_binding(value, ""))
            row.pack_start(clear, False, False, 0)
            shortcuts.pack_start(row, False, False, 0)
        actions = Gtk.Box(spacing=10)
        defaults = Gtk.Button(label="恢复默认")
        defaults.connect("clicked", self.restore_defaults)
        actions.pack_start(defaults, False, False, 0)
        save = Gtk.Button(label="保存快捷键")
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self.save)
        actions.pack_end(save, False, False, 0)
        shortcuts.pack_start(actions, False, False, 0)
        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.set_max_width_chars(48)
        shortcuts.pack_start(self.status, False, False, 0)
        if shortcut_settings() is None or not launcher_path().is_file():
            actions.set_sensitive(False)
            self.status.set_text("请先在 GNOME 桌面安装 zprint，再设置全局快捷键。")
        notebook.append_page(shortcuts, Gtk.Label(label="快捷键设置"))
        help_scroll = Gtk.ScrolledWindow()
        help_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.help_label = Gtk.Label(xalign=0, yalign=0, wrap=True, selectable=True, margin=20)
        self.help_label.set_max_width_chars(48)
        help_scroll.add(self.help_label)
        help_page = notebook.append_page(help_scroll, Gtk.Label(label="快捷键 / 帮助"))
        self.refresh_help()
        about = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=24,
                        halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name("zprint", Gtk.IconSize.DIALOG)
        icon.set_pixel_size(72)
        about.pack_start(icon, False, False, 0)
        title = Gtk.Label(label="zprint")
        title.get_style_context().add_class("hero")
        about.pack_start(title, False, False, 0)
        self.version_label = Gtk.Label(label=f"版本 {__version__}", selectable=True)
        about.pack_start(self.version_label, False, False, 0)
        about.pack_start(Gtk.Label(label="截图 · 标记 · 分享"), False, False, 0)
        notebook.append_page(about, Gtk.Label(label="关于 zprint"))
        self.show_all()
        if page == "help":
            notebook.set_current_page(help_page)

    def refresh_help(self):
        bindings = read_bindings(self.command)
        global_keys = "\n".join(f"{shortcut_label(bindings[action])}  {title}" for action, title, _ in SHORTCUTS)
        self.help_label.set_text(
            "系统快捷键\n" + global_keys +
            "\n\n编辑器内\n"
            "Ctrl+N  截图    Ctrl+O  导入    Ctrl+V  粘贴\n"
            "Ctrl+C  复制    Ctrl+S  导出\n"
            "Ctrl+Z  撤销    Ctrl+Shift+Z / Ctrl+Y  重做\n"
            "Ctrl+0  适应窗口    Ctrl+滚轮  缩放\n"
            "V / A / P / T / R / O / M / N  切换工具\n"
            "Delete  删除选中标记    Esc  取消当前绘制\n"
            "Shift+拖动  正圆 / 正方形    F1  打开此帮助页\n\n"
            "截图由系统界面完成，首次使用可能请求授权。\n"
            "复制图片后建议保留 zprint 窗口，直到完成粘贴。")

    def set_binding(self, action, binding):
        self.bindings[action] = binding
        self.buttons[action].set_label(shortcut_label(binding))
        self.status.set_text("尚未保存，点击“保存快捷键”应用修改。")

    def record(self, action):
        dialog = ShortcutRecorder(self)
        if dialog.run() == Gtk.ResponseType.OK:
            self.set_binding(action, dialog.binding)
        dialog.destroy()

    def restore_defaults(self, *_):
        for action, _, default in SHORTCUTS:
            self.set_binding(action, default)

    def save(self, *_):
        try:
            save_bindings(self.command, self.bindings)
        except ValueError as error:
            self.status.set_text(str(error))
            return
        self.bindings = read_bindings(self.command)
        self.refresh_help()
        self.status.set_text("快捷键已保存，立即生效。")
