import os
import unittest

from gi.repository import Gio

from zprint_app.shortcuts import (
    BASE, CUSTOM_SCHEMA, SHORTCUTS, identity, install_shortcuts, normalize_binding,
    read_bindings, save_bindings, shortcut_item, shortcut_path, shortcut_settings,
)


@unittest.skipUnless(os.environ.get("GSETTINGS_BACKEND") == "memory", "requires isolated settings backend")
class ShortcutTests(unittest.TestCase):
    def setUp(self):
        self.command = "/test/zprint"
        self.settings = shortcut_settings()
        self.settings.set_strv("custom-keybindings", [])
        for action, _, _ in SHORTCUTS:
            item = shortcut_item(action)
            for key in ("name", "command", "binding"):
                item.reset(key)
        self.values = {"capture": "<Primary><Alt>F8", "clipboard": "<Primary><Alt>F9"}

    def test_save_and_read_round_trip(self):
        save_bindings(self.command, self.values)
        actual = read_bindings(self.command)
        for action in self.values:
            self.assertEqual(identity(actual[action]), identity(self.values[action]))
            self.assertEqual(shortcut_item(action).get_string("command"), f"{self.command} --{action}")

    def test_alias_duplicate_rejected_without_partial_write(self):
        save_bindings(self.command, self.values)
        before = read_bindings(self.command)
        with self.assertRaises(ValueError):
            save_bindings(self.command, {"capture": "<Control><Alt>F8", "clipboard": "<Primary><Alt>F8"})
        self.assertEqual(read_bindings(self.command), before)

    def test_external_conflict_preserves_both_apps(self):
        save_bindings(self.command, self.values)
        path = BASE + "other-app/"
        item = Gio.Settings.new_with_path(CUSTOM_SCHEMA, path)
        item.set_string("binding", "<Primary><Alt>F10")
        item.set_string("name", "Other App")
        item.set_string("command", "other-app")
        self.settings.set_strv("custom-keybindings", [*self.settings.get_strv("custom-keybindings"), path])
        before = read_bindings(self.command)
        with self.assertRaisesRegex(ValueError, "Other App"):
            save_bindings(self.command, {"capture": "<Control><Alt>F10", "clipboard": "<Primary><Alt>F9"})
        self.assertEqual(read_bindings(self.command), before)
        self.assertEqual(item.get_string("command"), "other-app")
        self.assertIn(path, self.settings.get_strv("custom-keybindings"))

    def test_system_conflict_rejected(self):
        group = Gio.Settings.new("org.gnome.desktop.wm.keybindings")
        before = group.get_value("close")
        group.set_strv("close", ["<Primary><Alt>F8"])
        try:
            with self.assertRaises(ValueError):
                save_bindings(self.command, self.values)
            self.assertEqual(self.settings.get_strv("custom-keybindings"), [])
        finally:
            group.set_value("close", before)

    def test_swap_own_keys(self):
        save_bindings(self.command, self.values)
        swapped = {"capture": self.values["clipboard"], "clipboard": self.values["capture"]}
        save_bindings(self.command, swapped)
        for action in swapped:
            self.assertEqual(identity(read_bindings(self.command)[action]), identity(swapped[action]))

    def test_reinstall_preserves_custom_and_disabled_bindings(self):
        values = {**self.values, "clipboard": ""}
        save_bindings(self.command, values)
        install_shortcuts(self.command)
        self.assertEqual(read_bindings(self.command)["clipboard"], "")
        self.assertEqual(identity(read_bindings(self.command)["capture"]), identity(values["capture"]))

    def test_existing_foreign_command_is_not_overwritten(self):
        item = shortcut_item("capture")
        item.set_string("command", "other-app")
        self.settings.set_strv("custom-keybindings", [shortcut_path("capture")])
        with self.assertRaises(ValueError):
            save_bindings(self.command, self.values)
        self.assertEqual(item.get_string("command"), "other-app")

    def test_invalid_plain_key_does_not_write(self):
        for key in ("s", "<Shift>s", "NoSuchKey", "<Control>"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                save_bindings(self.command, {**self.values, "capture": key})
        self.assertEqual(self.settings.get_strv("custom-keybindings"), [])

    def test_modifier_alias_normalization(self):
        self.assertEqual(normalize_binding("<Primary><Alt>s"), normalize_binding("<Control><Alt>s"))
