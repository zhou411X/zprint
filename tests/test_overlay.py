from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from zprint_app.app import Zprint, Editor, identical_image
from gi.repository import Gdk, GLib, Gtk
from zprint_app.overlay import OverlayEditor
from zprint_app.model import Mark
from test_model import pixbuf
from test_ui import pump, test_application


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = test_application()

    def setUp(self):
        self.app.last_shell_token = None
        self.capture = {"token": "test-token", "image": [300, 200, 400, 200],
                        "monitor": [0, 0, 1920, 1080], "toolbar": [300, 408, 620, 54]}
        self.prepare = patch("zprint_app.shell_bridge.prepare", return_value=self.capture)
        self.prepare.start()
        self.dismiss = patch("zprint_app.shell_bridge.dismiss")
        self.dismiss.start()
        self.image = pixbuf(Image.new("RGB", (800, 400), "white"))
        self.window = OverlayEditor(self.app, self.image, self.capture)
        self.window.open()
        pump()

    def tearDown(self):
        self.app.last_shell_token = self.app.capture_shell_token = None
        for window in self.app.get_windows():
            window.destroy()
        self.prepare.stop()
        self.dismiss.stop()
        pump(.01)

    def test_original_pixel_coordinates_at_double_scale(self):
        canvas = self.window.canvas
        self.assertEqual(canvas.offset, (0, 0))
        start = SimpleNamespace(x=20, y=30, button=1, state=0, type=Gdk.EventType.BUTTON_PRESS)
        end = SimpleNamespace(x=160, y=90, button=1, state=0)
        canvas.press(canvas, start)
        canvas.release(canvas, end)
        self.assertEqual(self.window.document.marks[0].points, ((40, 60), (320, 180)))
        canvas.set_zoom(2)
        self.assertEqual(canvas.zoom, .5)

    def test_finish_copies_annotations_and_keeps_clipboard_owner_alive(self):
        self.window.document.add(Mark("rectangle", ((20, 20), (100, 100))))
        expected = self.window.document.pixbuf()
        self.window.finish()
        actual = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_image()
        self.assertTrue(identical_image(expected, actual))
        self.assertFalse(self.window.get_visible())
        self.assertFalse(self.window.bar_window.get_visible())
        self.assertIsNone(self.window.document)
        self.assertIn(self.window, self.app.get_windows())

    def test_expand_preserves_editable_history(self):
        doc = self.window.document
        doc.add(Mark("number", ((30, 30),)))
        self.window.expand()
        editor = self.app.editor()
        self.assertNotIsInstance(editor, OverlayEditor)
        self.assertIs(editor.document, doc)
        editor.undo()
        self.assertEqual(doc.marks, ())
        self.assertFalse(self.window.get_visible())

    def test_escape_cancels_stroke_then_discards_capture(self):
        canvas = self.window.canvas
        canvas.press(canvas, SimpleNamespace(x=20, y=30, button=1, state=0, type=Gdk.EventType.BUTTON_PRESS))
        event = SimpleNamespace(keyval=Gdk.KEY_Escape, state=0)
        self.window.key_press(self.window, event)
        self.assertTrue(self.window.get_visible())
        self.assertIsNone(canvas.draft)
        self.window.key_press(self.window, event)
        self.assertFalse(self.window.get_visible())

    def test_tools_sliders_and_undo_share_full_editor_model(self):
        self.window.width.set_value(12)
        self.window.font_size.set_value(48)
        for tool in self.window.tool_buttons:
            self.window.set_tool(tool)
            mark = self.window.new_mark(tool, ((10, 10),), "中文")
            self.assertEqual((mark.width, mark.font_size), (12, 48))
        self.window.document.add(Mark("number", ((30, 30),)))
        self.window.undo()
        self.assertEqual(self.window.document.marks, ())
        self.window.redo()
        self.assertEqual(len(self.window.document.marks), 1)

    def test_new_capture_discards_old_and_duplicate_delivery_does_not_reload(self):
        self.window.document.add(Mark("number", ((30, 30),)))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "new.png"
            Image.new("RGB", (800, 400), "blue").save(path)
            capture = dict(self.capture, uri=path.as_uri())
            self.app.show_shell_capture(capture)
            overlays = [w for w in self.app.get_windows() if isinstance(w, OverlayEditor)]
            self.assertEqual(len(overlays), 1)
            window = overlays[0]
            self.assertEqual(window.document.marks, ())
            self.assertFalse(window.document.can_undo)
            document = window.document
            document.add(Mark("number", ((10, 10),)))
            self.app.show_shell_capture(capture)
            self.assertIs(window.document, document)
            self.assertEqual(len(document.marks), 1)
            self.app.capture_shell_token = None
            self.app.hold()
            with patch("zprint_app.shell_bridge.get_capture", return_value=capture):
                self.app.capture_finished(path.as_uri(), None)
            self.assertEqual(len(self.app.get_windows()), 2)
            self.assertIs(window.document, document)

    def test_portal_error_before_shell_capture_does_not_grab_input(self):
        # GNOME can report closed before the image finishes saving. Exercise a
        # real dialog/main loop, not a mocked message() that hides GTK grabs.
        observed = []

        def inspect_dialog():
            observed.append(Gtk.grab_get_current())
            # Also lets the old, blocking implementation finish the test.
            if isinstance(observed[-1], Gtk.Dialog):
                observed[-1].response(Gtk.ResponseType.CLOSE)
            return GLib.SOURCE_REMOVE

        self.app.capture_shell_token = self.app.last_shell_token
        self.app.hold()
        GLib.idle_add(inspect_dialog)
        self.app.capture_finished(None, "系统截图失败，请检查桌面截图服务")
        pump()
        self.assertEqual(observed, [None], "A portal error must not block toolbar input")
        dialog = self.app.capture_error_dialog
        self.assertTrue(dialog.get_visible())
        self.assertFalse(dialog.get_modal())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "capture.png"
            self.image.savev(str(path), "png", [], [])
            self.app.show_shell_capture(dict(self.capture, uri=path.as_uri()))
        pump()
        self.assertIsNone(self.app.capture_error_dialog)
        self.assertIsNone(Gtk.grab_get_current())
        self.assertFalse(dialog.get_visible())

    def test_portal_failure_after_shell_capture_does_not_restore_old_windows(self):
        old = self.app.editor()
        old.hide()
        self.app.last_shell_token = self.capture["token"]
        for error in (None, "系统截图失败，请检查桌面截图服务"):
            with self.subTest(error=error), patch.object(Editor, "message") as message:
                self.app.capture_shell_token = "previous-capture"
                self.app.capture_windows = [old]
                self.app.hold()
                self.app.capture_finished(None, error)
                message.assert_not_called()
                self.assertFalse(old.get_visible())
                self.assertTrue(self.window.get_visible())
                self.assertTrue(self.window.bar_window.get_visible())
                self.assertEqual(self.app.capture_windows, [])
