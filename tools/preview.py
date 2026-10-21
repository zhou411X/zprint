"""Render an actual GTK window in an isolated display for visual review."""
import io
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cairo
from zprint_app.app import Zprint, Editor
from zprint_app.model import Mark
from gi.repository import GdkPixbuf, GLib


app = Zprint()
app.set_application_id("io.github.zprint.Preview")
app.register(None)
window = Editor(app)
surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 1000, 650)
ctx = cairo.Context(surface)
ctx.set_source_rgb(.95, .96, .98)
ctx.paint()
ctx.set_source_rgb(.13, .17, .24)
ctx.rectangle(0, 0, 1000, 60)
ctx.fill()
ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
ctx.set_font_size(22)
ctx.set_source_rgb(1, 1, 1)
ctx.move_to(32, 39)
ctx.show_text("PROJECT / OVERVIEW")
ctx.set_source_rgb(.18, .22, .30)
ctx.set_font_size(38)
ctx.move_to(55, 132)
ctx.show_text("Make your point.")
ctx.set_font_size(18)
ctx.set_source_rgb(.43, .48, .56)
ctx.move_to(55, 169)
ctx.show_text("A screenshot says more with a little annotation.")
for i, (title, value) in enumerate([("CAPTURES", "128"), ("ANNOTATIONS", "384"), ("SHARED", "96")]):
    x = 55 + i * 305
    ctx.set_source_rgb(1, 1, 1)
    ctx.rectangle(x, 214, 280, 150)
    ctx.fill()
    ctx.set_source_rgb(.45, .5, .58)
    ctx.set_font_size(14)
    ctx.move_to(x + 24, 250)
    ctx.show_text(title)
    ctx.set_source_rgb(.15, .2, .28)
    ctx.set_font_size(48)
    ctx.move_to(x + 24, 325)
    ctx.show_text(value)
ctx.set_source_rgb(1, 1, 1)
ctx.rectangle(55, 400, 890, 200)
ctx.fill()
ctx.set_source_rgb(.23, .57, .47)
for i, h in enumerate([45, 70, 53, 88, 110, 97, 145, 122, 160, 138, 170]):
    ctx.rectangle(85 + i * 75, 580 - h, 42, h)
    ctx.fill()
data = io.BytesIO()
surface.write_to_png(data)
loader = GdkPixbuf.PixbufLoader.new_with_type("png")
loader.write(data.getvalue())
loader.close()
window.load(loader.get_pixbuf(), "产品概览.png")
for mark in [Mark("rectangle", ((350, 209), (644, 369)), "#ff625c", 4),
             Mark("arrow", ((736, 181), (602, 240)), "#ff625c", 5),
             Mark("text", ((740, 145),), "#ff625c", text="这里是重点", font_size=26),
             Mark("number", ((343, 213),), "#ff625c", number=1),
             Mark("ellipse", ((787, 390), (928, 600)), "#68a7ff", 4),
             Mark("number", ((790, 400),), "#68a7ff", number=2)]:
    window.document.add(mark)
window.changed()


def save():
    rendered = cairo.ImageSurface(cairo.FORMAT_ARGB32, window.get_allocated_width(), window.get_allocated_height())
    window.draw(cairo.Context(rendered))
    rendered.write_to_png(sys.argv[1] if len(sys.argv) > 1 else "/tmp/zprint-preview.png")
    window.destroy()
    loop.quit()
    return GLib.SOURCE_REMOVE


loop = GLib.MainLoop()
GLib.timeout_add(500, save)
loop.run()
