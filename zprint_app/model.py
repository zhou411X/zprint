"""Image-space annotations. Preview, clipboard and export share one renderer."""

from dataclasses import dataclass, replace
import io
import math
from pathlib import Path

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GdkPixbuf, Pango, PangoCairo
from PIL import Image


@dataclass(frozen=True)
class Mark:
    tool: str
    points: tuple
    color: str = "#ff625c"
    width: float = 4.0
    text: str = ""
    number: int = 1
    font_size: int = 28

    def moved(self, dx, dy):
        return replace(self, points=tuple((x + dx, y + dy) for x, y in self.points))


def bounds(mark):
    xs, ys = zip(*mark.points)
    return min(xs), min(ys), max(xs), max(ys)


def text_layout(ctx, mark):
    layout = PangoCairo.create_layout(ctx)
    font = Pango.FontDescription("Sans")
    font.set_absolute_size(mark.font_size * Pango.SCALE)
    font.set_weight(Pango.Weight.BOLD)
    layout.set_font_description(font)
    layout.set_text(mark.text, -1)
    return layout


def mark_bounds(mark):
    x, y, right, bottom = bounds(mark)
    if mark.tool == "text":
        ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
        w, h = text_layout(ctx, mark).get_pixel_size()
        return x, y, x + w, y + h
    if mark.tool == "number":
        radius = max(14, mark.width * 3 + 6)
        return x - radius, y - radius, x + radius, y + radius
    return x, y, right, bottom


def color_rgb(value):
    return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))


def draw_mark(ctx, mark, surface):
    ctx.save()
    # Cairo's current path is not part of save/restore. In particular, Pango
    # leaves a current point which must not be joined to the next arc.
    ctx.new_path()
    ctx.set_source_rgb(*color_rgb(mark.color))
    ctx.set_line_width(mark.width)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    x, y = mark.points[0]
    ex, ey = mark.points[-1]
    left, top, right, bottom = bounds(mark)
    w, h = right - left, bottom - top
    if mark.tool == "pen":
        if len(mark.points) == 1:
            ctx.arc(x, y, mark.width / 2, 0, math.tau)
            ctx.fill()
        else:
            ctx.move_to(x, y)
            for point in mark.points[1:]:
                ctx.line_to(*point)
            ctx.stroke()
    elif mark.tool == "arrow":
        angle = math.atan2(ey - y, ex - x)
        head = min(math.hypot(ex - x, ey - y) * .6, max(14, mark.width * 4))
        ctx.move_to(x, y)
        ctx.line_to(ex, ey)
        ctx.stroke()
        ctx.move_to(ex - head * math.cos(angle - .48), ey - head * math.sin(angle - .48))
        ctx.line_to(ex, ey)
        ctx.line_to(ex - head * math.cos(angle + .48), ey - head * math.sin(angle + .48))
        ctx.stroke()
    elif mark.tool == "rectangle":
        ctx.rectangle(left, top, w, h)
        ctx.stroke()
    elif mark.tool == "ellipse" and w > 0 and h > 0:
        # Build the ellipse in scaled coordinates; stroke in image coordinates.
        ctx.save()
        ctx.translate(left + w / 2, top + h / 2)
        ctx.scale(w / 2, h / 2)
        ctx.arc(0, 0, 1, 0, math.tau)
        ctx.restore()
        ctx.stroke()
    elif mark.tool == "text":
        ctx.move_to(x, y)
        PangoCairo.show_layout(ctx, text_layout(ctx, mark))
    elif mark.tool == "number":
        radius = max(14, mark.width * 3 + 6)
        ctx.arc(x, y, radius, 0, math.tau)
        ctx.fill_preserve()
        ctx.set_line_width(2)
        ctx.set_source_rgb(1, 1, 1)
        ctx.stroke()
        label = replace(mark, text=str(mark.number), font_size=int(radius * 1.15))
        layout = text_layout(ctx, label)
        tw, th = layout.get_pixel_size()
        ctx.move_to(x - tw / 2, y - th / 2)
        PangoCairo.show_layout(ctx, layout)
    elif mark.tool == "mosaic":
        l, t = max(0, int(left)), max(0, int(top))
        r, b = min(surface.get_width(), math.ceil(right)), min(surface.get_height(), math.ceil(bottom))
        if r > l and b > t:
            surface.flush()
            # Read only the selected region, including all earlier annotations.
            pixbuf = Gdk.pixbuf_get_from_surface(surface, l, t, r - l, b - t)
            mode = "RGBA" if pixbuf.get_has_alpha() else "RGB"
            patch = Image.frombytes(mode, (r - l, b - t), pixbuf.get_pixels(),
                                    "raw", mode, pixbuf.get_rowstride())
            block = max(6, round(mark.width * 3))
            patch = patch.resize((max(1, (r - l) // block), max(1, (b - t) // block)), Image.Resampling.BOX)
            patch = patch.resize((r - l, b - t), Image.Resampling.NEAREST)
            data = io.BytesIO()
            patch.save(data, format="PNG")
            data.seek(0)
            tile = cairo.ImageSurface.create_from_png(data)
            ctx.set_source_surface(tile, l, t)
            ctx.rectangle(l, t, r - l, b - t)
            ctx.fill()
    ctx.new_path()
    ctx.restore()


class Document:
    def __init__(self, pixbuf, name="未命名"):
        self.image = pixbuf.copy()
        self.name = name
        self.width = pixbuf.get_width()
        self.height = pixbuf.get_height()
        self._history = [()]
        self._position = 0
        self._saved = ()
        self._cache = None

    @property
    def marks(self):
        return self._history[self._position]

    @property
    def dirty(self):
        return self.marks != self._saved

    @property
    def can_undo(self):
        return self._position > 0

    @property
    def can_redo(self):
        return self._position + 1 < len(self._history)

    @property
    def next_number(self):
        return max((m.number for m in self.marks if m.tool == "number"), default=0) + 1

    def commit(self, marks):
        marks = tuple(marks)
        if marks == self.marks:
            return
        del self._history[self._position + 1:]
        self._history.append(marks)
        self._position += 1
        self._cache = None

    def add(self, mark):
        self.commit((*self.marks, mark))

    def undo(self):
        if self.can_undo:
            self._position -= 1
            self._cache = None

    def redo(self):
        if self.can_redo:
            self._position += 1
            self._cache = None

    def render(self, marks=None):
        if marks is None and self._cache is not None:
            return self._cache
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.width, self.height)
        ctx = cairo.Context(surface)
        Gdk.cairo_set_source_pixbuf(ctx, self.image, 0, 0)
        ctx.paint()
        for mark in self.marks if marks is None else marks:
            draw_mark(ctx, mark, surface)
        surface.flush()
        if marks is None:
            self._cache = surface
        return surface

    def pixbuf(self):
        return Gdk.pixbuf_get_from_surface(self.render(), 0, 0, self.width, self.height)

    def export(self, path):
        suffix = Path(path).suffix.lower()
        if suffix == ".png":
            self.render().write_to_png(str(path))
        elif suffix in (".jpg", ".jpeg"):
            surface = cairo.ImageSurface(cairo.FORMAT_RGB24, self.width, self.height)
            ctx = cairo.Context(surface)
            ctx.set_source_rgb(1, 1, 1)
            ctx.paint()
            ctx.set_source_surface(self.render())
            ctx.paint()
            pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, self.width, self.height)
            pixbuf.savev(str(path), "jpeg", ["quality"], ["95"])
        else:
            raise ValueError("请使用 .png、.jpg 或 .jpeg 文件名")
        self._saved = self.marks

    def hit_test(self, x, y):
        for index in reversed(range(len(self.marks))):
            l, t, r, b = mark_bounds(self.marks[index])
            pad = max(7, self.marks[index].width)
            if l - pad <= x <= r + pad and t - pad <= y <= b + pad:
                return index
        return None
