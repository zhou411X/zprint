"""Shared GNOME shortcut configuration for the installer and preferences."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, Gtk

KEY_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA = KEY_SCHEMA + ".custom-keybinding"
BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
SHORTCUTS = (
    ("capture", "系统截图", "<Primary><Alt>s"),
    ("clipboard", "读取剪贴板图片", "<Primary><Alt>v"),
)


def shortcut_settings():
    source = Gio.SettingsSchemaSource.get_default()
    if not source.lookup(KEY_SCHEMA, True):
        return None
    return Gio.Settings.new(KEY_SCHEMA)


def shortcut_path(action):
    return BASE + "zprint-" + action + "/"


def shortcut_item(action):
    return Gio.Settings.new_with_path(CUSTOM_SCHEMA, shortcut_path(action))


def identity(binding):
    key, mods = Gtk.accelerator_parse(binding)
    return Gdk.keyval_to_lower(key), int(mods & Gtk.accelerator_get_default_mod_mask())


def shortcut_label(binding):
    if not binding or binding == "disabled":
        return "未设置"
    key, mods = Gtk.accelerator_parse(binding)
    return Gtk.accelerator_get_label(key, mods)


def occupied_shortcuts(exclude=()):
    occupied = {}

    def remember(binding, owner):
        if binding and binding != "disabled":
            key = identity(binding)
            if key[0]:
                occupied[key] = owner

    settings = shortcut_settings()
    if settings:
        for path in settings.get_strv("custom-keybindings"):
            if path not in exclude:
                item = Gio.Settings.new_with_path(CUSTOM_SCHEMA, path)
                remember(item.get_string("binding"), item.get_string("name") or path)
    source = Gio.SettingsSchemaSource.get_default()
    for name in ("org.gnome.desktop.wm.keybindings", "org.gnome.shell.keybindings", KEY_SCHEMA):
        schema = source.lookup(name, True)
        if not schema:
            continue
        group = Gio.Settings.new(name)
        for key in schema.list_keys():
            value = group.get_value(key)
            if value.get_type_string() == "as" and key != "custom-keybindings":
                for binding in value.unpack():
                    remember(binding, f"{name}:{key}")
    return occupied


def read_bindings(command):
    settings = shortcut_settings()
    paths = settings.get_strv("custom-keybindings") if settings else []
    return {
        action: shortcut_item(action).get_string("binding")
        if shortcut_path(action) in paths and shortcut_item(action).get_string("command") == f"{command} --{action}"
        else ""
        for action, _, _ in SHORTCUTS
    } if settings else {action: "" for action, _, _ in SHORTCUTS}


def normalize_binding(binding):
    if not binding or binding == "disabled":
        return ""
    key, mods = Gtk.accelerator_parse(binding)
    modifier = mods & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.SUPER_MASK)
    standalone = key == Gdk.KEY_Print or Gdk.KEY_F1 <= key <= Gdk.KEY_F35
    if not key or (not modifier and not standalone) or not Gtk.accelerator_valid(key, mods):
        raise ValueError("请使用 Ctrl、Alt 或 Super 加其他按键的组合，或功能键。")
    return Gtk.accelerator_name(Gdk.keyval_to_lower(key), mods)


def save_bindings(command, bindings):
    settings = shortcut_settings()
    if settings is None:
        raise ValueError("当前桌面不支持 GNOME 全局快捷键设置。")
    paths = list(settings.get_strv("custom-keybindings"))
    items = {action: shortcut_item(action) for action, _, _ in SHORTCUTS}
    for action, item in items.items():
        existing = item.get_string("command")
        if existing and existing != f"{command} --{action}":
            raise ValueError("zprint 的快捷键配置已被其他命令占用，请先在系统键盘设置中处理。")
        if not all(item.is_writable(key) for key in ("name", "command", "binding")):
            raise ValueError("系统不允许修改这些快捷键。")
    if not settings.is_writable("custom-keybindings"):
        raise ValueError("系统不允许修改全局快捷键列表。")
    values = {action: normalize_binding(bindings[action]) for action in items}
    occupied = occupied_shortcuts(exclude=[shortcut_path(action) for action in items])
    for action, title, _ in SHORTCUTS:
        value = values[action]
        if not value:
            continue
        key = identity(value)
        if key in occupied:
            raise ValueError(f"{shortcut_label(value)} 已用于“{occupied[key]}”，请换一个组合键。")
        occupied[key] = title
    # Validate both rows before writing anything, including when swapping keys.
    for action, title, _ in SHORTCUTS:
        item = items[action]
        item.delay()
        item.set_string("name", "zprint — " + title)
        item.set_string("command", f"{command} --{action}")
        item.set_string("binding", values[action])
        item.apply()
        path = shortcut_path(action)
        if path not in paths:
            paths.append(path)
    settings.set_strv("custom-keybindings", paths)
    Gio.Settings.sync()


def install_shortcuts(command):
    settings = shortcut_settings()
    if settings is None:
        print("未检测到 GNOME 快捷键设置，请在系统设置中绑定 zprint --capture / --clipboard。")
        return
    paths = list(settings.get_strv("custom-keybindings"))
    occupied = occupied_shortcuts()
    for action, title, binding in SHORTCUTS:
        path = shortcut_path(action)
        item = shortcut_item(action)
        if path in paths:
            print(f"保留已有快捷键配置：{path}")
            continue
        owner = occupied.get(identity(binding))
        if owner:
            print(f"跳过 {binding}：已被 {owner} 使用，可在设置中手动绑定 --{action}。")
            continue
        item.set_string("name", "zprint — " + title)
        item.set_string("command", f"{command} --{action}")
        item.set_string("binding", binding)
        paths.append(path)
        occupied[identity(binding)] = title
        print(f"已设置快捷键：{binding} → zprint --{action}")
    settings.set_strv("custom-keybindings", paths)
    Gio.Settings.sync()
