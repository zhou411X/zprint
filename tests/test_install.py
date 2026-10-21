import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gi.repository import Gio

import install


@unittest.skipUnless(os.environ.get("GSETTINGS_BACKEND") == "memory", "requires isolated settings backend")
class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = {"DATA": root / "share", "DEST": root / "share/zprint", "BIN": root / "bin/zprint",
                      "DESKTOP": root / "share/applications/zprint.desktop", "ICON": root / "share/icons/zprint.svg"}
        self.patcher = patch.multiple(install, **self.paths)
        self.patcher.start()
        self.settings = install.shortcut_settings()
        self.settings.set_strv("custom-keybindings", [])
        for suffix in ("capture", "clipboard"):
            item = Gio.Settings.new_with_path(install.CUSTOM_SCHEMA, install.BASE + "zprint-" + suffix + "/")
            for key in ("name", "binding", "command"):
                item.reset(key)

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def test_install_and_repeat_preserve_existing_shortcuts(self):
        original = install.BASE + "other/"
        item = Gio.Settings.new_with_path(install.CUSTOM_SCHEMA, original)
        item.set_string("binding", "<Primary><Alt>x")
        item.set_string("command", "other-app")
        self.settings.set_strv("custom-keybindings", [original])
        with patch("sys.argv", ["install.py"]):
            install.main()
            install.main()
        paths = self.settings.get_strv("custom-keybindings")
        self.assertEqual(len(paths), 3)
        self.assertIn(original, paths)
        self.assertEqual(item.get_string("command"), "other-app")
        self.assertTrue(self.paths["BIN"].stat().st_mode & 0o100)
        self.assertIn("--capture", self.paths["DESKTOP"].read_text())
        self.assertTrue((self.paths["DEST"] / "zprint_app/app.py").is_file())

    def test_conflicting_shortcut_is_skipped(self):
        original = install.BASE + "occupied/"
        item = Gio.Settings.new_with_path(install.CUSTOM_SCHEMA, original)
        item.set_string("binding", "<Control><Alt>s")
        item.set_string("command", "other-app")
        self.settings.set_strv("custom-keybindings", [original])
        install.install_shortcuts("/test/zprint")
        self.assertNotIn(install.BASE + "zprint-capture/", self.settings.get_strv("custom-keybindings"))
        self.assertEqual(item.get_string("binding"), "<Control><Alt>s")

    def test_unknown_install_directory_is_not_overwritten(self):
        self.paths["DEST"].mkdir(parents=True)
        with patch("sys.argv", ["install.py"]), self.assertRaises(SystemExit):
            install.main()

    def test_extension_install_enable_and_uninstall_preserve_other_extensions(self):
        shell = Gio.Settings.new("org.gnome.shell")
        shell.set_strv("enabled-extensions", ["other@example"])
        shell.set_boolean("disable-user-extensions", True)
        with patch("sys.argv", ["install.py", "--enable-shell-extension"]):
            install.main()
        extension = self.paths["DATA"] / "gnome-shell/extensions" / install.EXTENSION_UUID
        self.assertTrue((extension / "extension.js").is_file())
        self.assertEqual(shell.get_strv("enabled-extensions"), ["other@example", install.EXTENSION_UUID])
        self.assertFalse(shell.get_boolean("disable-user-extensions"))
        install.uninstall()
        self.assertEqual(shell.get_strv("enabled-extensions"), ["other@example"])
        self.assertFalse(extension.exists())

    def test_uninstall_removes_only_zprint_shortcuts(self):
        original = install.BASE + "other/"
        self.settings.set_strv("custom-keybindings", [original])
        with patch("sys.argv", ["install.py"]):
            install.main()
        install.uninstall()
        self.assertEqual(self.settings.get_strv("custom-keybindings"), [original])
        self.assertFalse(self.paths["BIN"].exists())
        self.assertFalse(self.paths["DEST"].exists())
