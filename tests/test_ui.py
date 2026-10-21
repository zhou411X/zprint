from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cairo
from PIL import Image

from zprint_app.app import Zprint, Editor, identical_image
from zprint_app.model import Mark
from zprint_app import __version__
from zprint_app.preferences import Preferences, ShortcutRecorder, launcher_command
from zprint_app.shortcuts import identity, read_bindings
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk
from test_model import pixbuf


def pump(seconds=.05):
    end = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(.001)


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Zprint()
        cls.app.set_application_id("io.github.zprint.Test")
        cls.app.register(None)

    def setUp(self):
        self.window = Editor(self.app)
        self.window.load(pixbuf(Image.new("RGB", (640, 400), "white")), "测试图片")
        pump()

    def tearDown(self):
        self.window.destroy()
        pump(.01)

    def event(self, x, y, **extra):
        canvas = self.window.canvas
        return SimpleNamespace(x=canvas.offset[0] + x * canvas.zoom,
                               y=canvas.offset[1] + y * canvas.zoom,
                               button=1, state=0, type=Gdk.EventType.BUTTON_PRESS, **extra)

    def test_window_renders_and_all_tools_switch(self):
        for tool in self.window.tool_buttons:
            self.window.set_tool(tool)
            self.assertTrue(self.window.tool_buttons[tool].get_active())
        pump()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1160, 780)
        self.window.draw(cairo.Context(surface))
        self.assertEqual(self.window.dimensions.get_text(), "640 × 400 px")

    def test_preferences_version_and_unsaved_changes(self):
        dialog = Preferences(self.window)
        before = read_bindings(dialog.command)
        dialog.restore_defaults()
        dialog.set_binding("capture", "<Primary><Alt>F8")
        self.assertIn(__version__, dialog.version_label.get_text())
        self.assertEqual(read_bindings(dialog.command), before)
        dialog.destroy()
        reopened = Preferences(self.window)
        self.assertEqual(reopened.bindings, before)
        reopened.destroy()

    def test_deb_preferences_use_system_launcher(self):
        with patch("zprint_app.preferences.__file__", "/usr/lib/zprint/zprint_app/preferences.py"):
            self.assertEqual(launcher_command(), "/usr/bin/zprint")

    def test_deb_shortcuts_register_once_in_user_application(self):
        with patch.object(self.app, "shortcuts_ready", False), \
             patch("zprint_app.app.launcher_path", return_value=Path("/usr/bin/zprint")), \
             patch("zprint_app.app.launcher_command", return_value="/usr/bin/zprint"), \
             patch("zprint_app.app.install_shortcuts") as install:
            self.app.ensure_shortcuts()
            self.app.ensure_shortcuts()
            install.assert_called_once_with("/usr/bin/zprint")

    def test_shortcut_recorder_validates_and_records(self):
        dialog = ShortcutRecorder(self.window)
        with patch.object(dialog, "response") as response:
            dialog.key_pressed(dialog, SimpleNamespace(keyval=Gdk.KEY_s, state=0, is_modifier=False))
            response.assert_not_called()
            dialog.key_pressed(dialog, SimpleNamespace(keyval=Gdk.KEY_s,
                state=Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK, is_modifier=False))
            response.assert_called_once_with(Gtk.ResponseType.OK)
        self.assertEqual(identity(dialog.binding), identity("<Primary><Alt>s"))
        dialog.destroy()

    def test_drag_draw_undo_redo_at_scaled_coordinates(self):
        canvas = self.window.canvas
        canvas.set_zoom(.5)
        pump()
        canvas.press(canvas, self.event(40, 40))
        canvas.motion(canvas, self.event(180, 100))
        canvas.release(canvas, self.event(180, 100))
        mark = self.window.document.marks[0]
        self.assertEqual(mark.points, ((40, 40), (180, 100)))
        self.window.undo()
        self.assertEqual(len(self.window.document.marks), 0)
        self.window.redo()
        self.assertEqual(len(self.window.document.marks), 1)

    def test_select_move_and_delete(self):
        doc, canvas = self.window.document, self.window.canvas
        doc.add(Mark("rectangle", ((40, 40), (100, 100))))
        self.window.set_tool("select")
        canvas.press(canvas, self.event(60, 60))
        canvas.release(canvas, self.event(80, 70))
        self.assertEqual(doc.marks[0].points[0], (60, 50))
        self.window.delete_selected()
        self.assertEqual(doc.marks, ())
        self.window.undo()
        self.assertEqual(len(doc.marks), 1)

    def test_escape_cancels_uncommitted_stroke(self):
        canvas = self.window.canvas
        canvas.press(canvas, self.event(40, 40))
        canvas.motion(canvas, self.event(100, 100))
        canvas.cancel()
        canvas.release(canvas, self.event(150, 150))
        self.assertEqual(self.window.document.marks, ())

    def test_clipboard_round_trip_includes_annotations(self):
        self.window.document.add(Mark("arrow", ((40, 40), (200, 100))))
        self.window.copy()
        image = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_image()
        self.assertIsNotNone(image)
        self.assertTrue(identical_image(image, self.window.document.pixbuf()))

    def test_paste_discards_saved_and_unsaved_marks_without_confirmation(self):
        for saved in (False, True):
            with self.subTest(saved=saved), tempfile.TemporaryDirectory() as folder:
                original = self.window.document
                original.add(Mark("number", ((10, 10),)))
                if saved:
                    original.export(Path(folder) / "old.png")
                self.assertEqual(original.dirty, not saved)
                self.window.canvas.selected = 0
                image = pixbuf(Image.new("RGB", (30, 40), "blue"))
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_image(image)
                with patch.object(self.window, "confirm_replace", return_value=False) as confirm:
                    self.window.paste()
                    pump(.35)
                confirm.assert_not_called()
                self.assertIsNot(self.window.document, original)
                self.assertTrue(identical_image(self.window.document.pixbuf(), image))
                self.assertEqual(self.window.document.marks, ())
                self.assertFalse(self.window.document.can_undo)
                self.assertFalse(self.window.document.can_redo)
                self.assertIsNone(self.window.canvas.selected)

    def test_clipboard_command_reuses_existing_window(self):
        self.window.document.add(Mark("number", ((40, 40),)))
        image = pixbuf(Image.new("RGB", (30, 40), "blue"))
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_image(image)
        command = SimpleNamespace(get_arguments=lambda: ["zprint", "--clipboard"])
        with patch.object(self.window, "confirm_replace", return_value=False) as confirm:
            self.assertEqual(self.app.do_command_line(command), 0)
            pump(.35)
        confirm.assert_not_called()
        self.assertEqual(self.app.get_windows(), [self.window])
        self.assertTrue(identical_image(self.window.document.pixbuf(), image))

    def test_empty_clipboard_reports_message(self):
        original = self.window.document
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text("not an image", -1)
        with patch.object(self.window, "message") as message:
            self.window.paste()
            pump(.35)
        message.assert_called_once()
        self.assertIs(self.window.document, original)

    def test_capture_cancel_restores_existing_window(self):
        with patch("zprint_app.app.ScreenshotRequest"):
            self.app.capture()
            self.assertFalse(self.window.get_visible())
            self.app.capture_finished(None, None)
        self.assertTrue(self.window.get_visible())

    def test_capture_result_replaces_saved_and_unsaved_document(self):
        for saved in (False, True):
            with self.subTest(saved=saved), tempfile.TemporaryDirectory() as folder:
                before = self.window.document
                before.add(Mark("number", ((10, 10),)))
                if saved:
                    before.export(Path(folder) / "old.png")
                self.assertEqual(before.dirty, not saved)
                path = Path(folder) / "capture.png"
                Image.new("RGB", (50, 60), "red").save(path)
                with patch.object(self.window, "confirm_replace", return_value=False) as confirm:
                    self.app.hold()
                    self.app.capture_finished(path.as_uri(), None)
                    pump(.3)
                confirm.assert_not_called()
                self.assertEqual(self.app.get_windows(), [self.window])
                self.assertIsNot(self.window.document, before)
                self.assertTrue(identical_image(self.window.document.pixbuf(), GdkPixbuf.Pixbuf.new_from_file(str(path))))
                self.assertEqual(self.window.document.marks, ())
                self.assertFalse(self.window.document.can_undo)
                self.assertFalse(self.window.document.can_redo)
