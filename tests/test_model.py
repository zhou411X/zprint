import io
from pathlib import Path
import tempfile
import unittest

from gi.repository import GLib
from PIL import Image, ImageChops

from zprint_app.model import Document, Mark
from zprint_app.app import identical_image
from gi.repository import GdkPixbuf


def pixbuf(image):
    data = io.BytesIO()
    image.save(data, format="PNG")
    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(data.getvalue())
    loader.close()
    return loader.get_pixbuf()


def rendered(document):
    data = io.BytesIO()
    document.render().write_to_png(data)
    data.seek(0)
    return Image.open(data).convert("RGBA")


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new("RGBA", (240, 160), "white")
        self.doc = Document(pixbuf(self.image))

    def test_each_tool_changes_pixels_and_undo_restores(self):
        for tool in ("arrow", "pen", "rectangle", "ellipse", "text", "number"):
            with self.subTest(tool=tool):
                self.doc.add(Mark(tool, ((30, 30), (100, 90)), text="中文 Text"))
                diff = ImageChops.difference(rendered(self.doc).convert("RGB"), self.image.convert("RGB"))
                self.assertIsNotNone(diff.getbbox())
                self.doc.undo()
                self.assertEqual(rendered(self.doc).tobytes(), self.image.tobytes())

    def test_reverse_drag_shapes_render_identically(self):
        for tool in ("rectangle", "ellipse", "mosaic"):
            with self.subTest(tool=tool):
                a = Document(pixbuf(self.image))
                b = Document(pixbuf(self.image))
                a.add(Mark(tool, ((20, 30), (150, 120))))
                b.add(Mark(tool, ((150, 120), (20, 30))))
                self.assertEqual(rendered(a).tobytes(), rendered(b).tobytes())

    def test_single_point_pen_draws_dot(self):
        self.doc.add(Mark("pen", ((40, 40),)))
        self.assertNotEqual(rendered(self.doc).getpixel((40, 40)), (255, 255, 255, 255))

    def test_text_does_not_connect_to_next_circle(self):
        self.doc.add(Mark("text", ((20, 20),), text="X"))
        self.doc.add(Mark("ellipse", ((140, 80), (200, 140))))
        result = rendered(self.doc)
        self.assertEqual(result.crop((65, 45, 110, 75)).tobytes(), self.image.crop((65, 45, 110, 75)).tobytes())

    def test_mosaic_changes_region_and_preserves_outside(self):
        image = Image.new("RGB", (64, 64))
        image.putdata([(255 if (x + y) % 2 else 0, x * 4, y * 4) for y in range(64) for x in range(64)])
        self.doc = Document(pixbuf(image))
        self.doc.add(Mark("mosaic", ((16, 16), (48, 48)), width=4))
        result = rendered(self.doc).convert("RGB")
        self.assertEqual(result.getpixel((0, 0)), image.getpixel((0, 0)))
        self.assertEqual(result.crop((0, 0, 16, 64)).tobytes(), image.crop((0, 0, 16, 64)).tobytes())
        self.assertNotEqual(result.crop((16, 16, 48, 48)).tobytes(), image.crop((16, 16, 48, 48)).tobytes())
        self.assertEqual(result.getpixel((20, 20)), result.getpixel((21, 20)))

    def test_mosaic_includes_earlier_annotations(self):
        self.doc.add(Mark("pen", ((20, 40), (150, 40)), width=4))
        before = rendered(self.doc)
        self.doc.add(Mark("mosaic", ((10, 10), (170, 80)), width=8))
        self.assertNotEqual(rendered(self.doc).tobytes(), before.tobytes())

    def test_mosaic_outside_image_is_clipped(self):
        self.doc.add(Mark("mosaic", ((-100, -100), (300, 200))))
        self.assertEqual(rendered(self.doc).size, (240, 160))

    def test_undo_redo_and_branch_history(self):
        a = Mark("number", ((40, 40),), number=1)
        b = Mark("number", ((100, 40),), number=2)
        self.doc.add(a)
        self.doc.add(b)
        self.assertEqual(self.doc.next_number, 3)
        self.doc.undo()
        self.assertEqual(self.doc.next_number, 2)
        self.doc.redo()
        self.assertEqual(self.doc.marks, (a, b))
        self.doc.undo()
        self.doc.add(a.moved(10, 10))
        self.assertFalse(self.doc.can_redo)

    def test_move_and_delete_are_undoable(self):
        a = Mark("rectangle", ((30, 30), (80, 80)))
        self.doc.add(a)
        self.doc.commit([a.moved(30, 10)])
        self.assertEqual(self.doc.marks[0].points[0], (60, 40))
        self.doc.commit([])
        self.doc.undo()
        self.doc.undo()
        self.assertEqual(self.doc.marks, (a,))

    def test_hit_testing_picks_topmost_text_and_number(self):
        self.doc.add(Mark("text", ((20, 20),), text="Hello"))
        self.assertEqual(self.doc.hit_test(50, 30), 0)
        self.doc.add(Mark("number", ((50, 30),)))
        self.assertEqual(self.doc.hit_test(50, 30), 1)
        self.assertIsNone(self.doc.hit_test(230, 150))

    def test_export_png_matches_clipboard_pixels(self):
        self.doc.add(Mark("arrow", ((30, 30), (150, 100))))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "标记.png"
            self.doc.export(path)
            self.assertTrue(identical_image(self.doc.pixbuf(), GdkPixbuf.Pixbuf.new_from_file(str(path))))
            self.assertFalse(self.doc.dirty)
            self.doc.undo()
            self.assertTrue(self.doc.dirty)
            self.doc.redo()
            self.assertFalse(self.doc.dirty)

    def test_transparency_png_and_white_jpeg(self):
        doc = Document(pixbuf(Image.new("RGBA", (20, 20), (0, 0, 0, 0))))
        with tempfile.TemporaryDirectory() as folder:
            png, jpg = Path(folder) / "x.png", Path(folder) / "x.jpg"
            doc.export(png)
            doc.export(jpg)
            with Image.open(png) as image:
                self.assertEqual(image.getpixel((5, 5))[3], 0)
            with Image.open(jpg) as image:
                self.assertEqual(image.getpixel((5, 5)), (255, 255, 255))

    def test_export_error_does_not_mark_saved(self):
        self.doc.add(Mark("pen", ((30, 30),)))
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                self.doc.export(Path(folder) / "bad.pdf")
            self.assertTrue(self.doc.dirty)

    def test_image_comparison_handles_padding_and_channels(self):
        rgb = pixbuf(Image.new("RGB", (7, 5), "red"))
        rgba = pixbuf(Image.new("RGBA", (7, 5), "red"))
        self.assertTrue(identical_image(rgb, rgba))
        self.assertFalse(identical_image(rgb, pixbuf(Image.new("RGB", (7, 5), "blue"))))
        self.assertFalse(identical_image(rgb, pixbuf(Image.new("RGB", (8, 5), "red"))))
