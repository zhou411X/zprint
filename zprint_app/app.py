"""GTK desktop application. No X11 key injection or background clipboard polling."""

from dataclasses import replace
from datetime import datetime
import math
from pathlib import Path
import sys

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from .capture import ScreenshotRequest
from .model import Document, Mark, draw_mark, mark_bounds
from .preferences import Preferences, launcher_command, launcher_path
from .shortcuts import install_shortcuts


TOOLS = [
    ("select", "↖", "选择 / 移动", "V"),
    ("arrow", "↗", "箭头", "A"),
    ("pen", "✎", "画笔", "P"),
    ("text", "T", "文本", "T"),
    ("rectangle", "□", "矩形", "R"),
    ("ellipse", "○", "圆形", "O"),
    ("mosaic", "▦", "打码", "M"),
    ("number", "①", "数字", "N"),
]
COLORS = ["#ff625c", "#ffba59", "#f8e66e", "#a4e8d1", "#68a7ff", "#c59aff", "#ffffff", "#20242d"]


def button(label, callback, tooltip=None, css=None):
    widget = Gtk.Button(label=label)
    widget.connect("clicked", lambda *_: callback())
    if tooltip:
        widget.set_tooltip_text(tooltip)
    if css:
        widget.get_style_context().add_class(css)
    return widget


def label(text, css=None, xalign=0):
    widget = Gtk.Label(label=text, xalign=xalign)
    if css:
        widget.get_style_context().add_class(css)
    return widget


def identical_image(a, b):
    if (a.get_width(), a.get_height()) != (b.get_width(), b.get_height()):
        return False
    # Compare visible RGBA pixels, excluding rowstride padding.
    a, b = a.add_alpha(False, 0, 0, 0), b.add_alpha(False, 0, 0, 0)
    ap, bp = a.get_pixels(), b.get_pixels()
    n = a.get_width() * 4
    return all(ap[y * a.get_rowstride():y * a.get_rowstride() + n] ==
               bp[y * b.get_rowstride():y * b.get_rowstride() + n]
               for y in range(a.get_height()))


class Canvas(Gtk.DrawingArea):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.zoom = 1.0
        self.offset = (0, 0)
        self.start = None
        self.draft = None
        self.selected = None
        self.original = None
        self.set_can_focus(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK |
                        Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.connect("draw", self.draw)
        self.connect("button-press-event", self.press)
        self.connect("motion-notify-event", self.motion)
        self.connect("button-release-event", self.release)
        self.connect("scroll-event", self.scroll)

    def reset(self):
        self.cancel()
        self.selected = None

    def cancel(self):
        self.start = self.draft = self.original = None
        self.queue_draw()

    def set_zoom(self, zoom):
        self.zoom = max(.1, min(4, zoom))
        doc = self.editor.document
        if doc:
            self.set_size_request(math.ceil(doc.width * self.zoom) + 64,
                                  math.ceil(doc.height * self.zoom) + 64)
        self.editor.zoom_label.set_text(f"{round(self.zoom * 100)}%")
        self.queue_draw()

    def position(self, event, clamp=False):
        doc = self.editor.document
        x = (event.x - self.offset[0]) / self.zoom
        y = (event.y - self.offset[1]) / self.zoom
        if clamp:
            return max(0, min(doc.width - 1, x)), max(0, min(doc.height - 1, y))
        if 0 <= x < doc.width and 0 <= y < doc.height:
            return x, y
        return None

    def draw(self, widget, ctx):
        ctx.set_source_rgb(.105, .12, .15)
        ctx.paint()
        doc = self.editor.document
        if not doc:
            return False
        w, h = doc.width * self.zoom, doc.height * self.zoom
        ox = max(32, (self.get_allocated_width() - w) / 2)
        oy = max(32, (self.get_allocated_height() - h) / 2)
        self.offset = ox, oy
        ctx.set_source_rgba(0, 0, 0, .35)
        ctx.rectangle(ox + 5, oy + 7, w, h)
        ctx.fill()
        ctx.save()
        ctx.translate(ox, oy)
        ctx.scale(self.zoom, self.zoom)
        ctx.rectangle(0, 0, doc.width, doc.height)
        ctx.clip()
        # Checkerboard stays small even for large source images.
        checker = cairo.ImageSurface(cairo.FORMAT_RGB24, 24, 24)
        cc = cairo.Context(checker)
        cc.set_source_rgb(.93, .94, .95)
        cc.paint()
        cc.set_source_rgb(.83, .85, .87)
        cc.rectangle(0, 0, 12, 12)
        cc.rectangle(12, 12, 12, 12)
        cc.fill()
        pattern = cairo.SurfacePattern(checker)
        pattern.set_extend(cairo.EXTEND_REPEAT)
        ctx.set_source(pattern)
        ctx.paint()
        if self.original is not None and self.draft is not None:
            marks = list(doc.marks)
            marks[self.selected] = self.draft
            surface = doc.render(marks)
        else:
            surface = doc.render()
        ctx.set_source_surface(surface)
        ctx.paint()
        if self.draft is not None and self.original is None:
            if self.draft.tool == "mosaic":
                l, t, r, b = mark_bounds(self.draft)
                ctx.set_source_rgba(.64, .91, .82, .3)
                ctx.rectangle(l, t, r - l, b - t)
                ctx.fill_preserve()
                ctx.set_source_rgb(.64, .91, .82)
                ctx.set_line_width(1 / self.zoom)
                ctx.stroke()
            else:
                draw_mark(ctx, self.draft, surface)
        if self.selected is not None and self.selected < len(doc.marks):
            mark = self.draft if self.original is not None else doc.marks[self.selected]
            l, t, r, b = mark_bounds(mark)
            ctx.set_source_rgb(.2, .65, .95)
            ctx.set_line_width(1.5 / self.zoom)
            ctx.set_dash([5 / self.zoom, 4 / self.zoom])
            ctx.rectangle(l - 5, t - 5, r - l + 10, b - t + 10)
            ctx.stroke()
        ctx.restore()
        return False

    def press(self, widget, event):
        if event.button != 1 or not self.editor.document:
            return False
        self.grab_focus()
        point = self.position(event)
        if point is None:
            return False
        doc = self.editor.document
        tool = self.editor.tool
        if tool == "select":
            self.selected = doc.hit_test(*point)
            if self.selected is not None:
                mark = doc.marks[self.selected]
                if event.type == Gdk.EventType._2BUTTON_PRESS and mark.tool == "text":
                    self.cancel()
                    self.editor.edit_text(point, self.selected)
                    return True
                self.original = mark
                self.draft = mark
                self.start = point
            self.queue_draw()
            return True
        self.selected = None
        if tool == "text":
            self.editor.edit_text(point)
        elif tool == "number":
            doc.add(self.editor.new_mark(tool, (point,)))
            self.editor.changed()
        else:
            self.start = point
            self.draft = self.editor.new_mark(tool, (point,))
        return True

    def motion(self, widget, event):
        if self.start is None:
            return False
        point = self.position(event, clamp=True)
        if self.original is not None:
            self.draft = self.original.moved(point[0] - self.start[0], point[1] - self.start[1])
        elif self.draft.tool == "pen":
            self.draft = replace(self.draft, points=(*self.draft.points, point))
        else:
            if event.state & Gdk.ModifierType.SHIFT_MASK and self.draft.tool in ("rectangle", "ellipse"):
                dx, dy = point[0] - self.start[0], point[1] - self.start[1]
                side = min(abs(dx), abs(dy))
                point = self.start[0] + math.copysign(side, dx), self.start[1] + math.copysign(side, dy)
            self.draft = replace(self.draft, points=(self.start, point))
        self.queue_draw()
        return True

    def release(self, widget, event):
        if event.button != 1 or self.start is None:
            return False
        self.motion(widget, event)
        doc = self.editor.document
        if self.original is not None:
            marks = list(doc.marks)
            marks[self.selected] = self.draft
            doc.commit(marks)
        elif self.draft.tool == "pen" or math.dist(self.draft.points[0], self.draft.points[-1]) >= 2:
            doc.add(self.draft)
        self.cancel()
        self.editor.changed()
        return True

    def scroll(self, widget, event):
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            if event.direction == Gdk.ScrollDirection.SMOOTH:
                _, _, dy = event.get_scroll_deltas()
            else:
                dy = -1 if event.direction == Gdk.ScrollDirection.UP else 1
            self.set_zoom(self.zoom * (1.1 if dy < 0 else 1 / 1.1))
            return True
        return False


class Editor(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="zprint")
        self.document = None
        self.tool = "arrow"
        self.color = COLORS[0]
        self._paste_serial = 0
        self.set_default_size(1160, 780)
        self.set_size_request(860, 560)
        self.connect("delete-event", self.close_requested)
        self.connect("key-press-event", self.key_press)
        header = Gtk.HeaderBar(title="zprint", subtitle="截图 · 标记 · 分享", show_close_button=True)
        self.set_titlebar(header)
        header.pack_start(button("＋ 截图", app.capture, "系统截图  Ctrl+N", "suggested-action"))
        header.pack_start(button("导入", self.open_file, "导入图片  Ctrl+O"))
        header.pack_start(button("粘贴", self.paste, "读取剪贴板图片  Ctrl+V"))
        self.copy_button = button("复制图片", self.copy, "复制标记后的图片  Ctrl+C", "suggested-action")
        header.pack_start(self.copy_button)
        header.pack_start(button("导出…", self.export, "导出 PNG / JPEG  Ctrl+S"))

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)
        body = Gtk.Box()
        root.pack_start(body, True, True, 0)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        sidebar.set_size_request(174, -1)
        sidebar.get_style_context().add_class("sidebar")
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_min_content_width(174)
        sidebar_scroll.add(sidebar)
        body.pack_start(sidebar_scroll, False, False, 0)
        sidebar.pack_start(label("标记工具", "section"), False, False, 8)
        self.tool_buttons = {}
        self.tool_handlers = {}
        for tool, symbol, title, key in TOOLS:
            toggle = Gtk.ToggleButton()
            row = Gtk.Box(spacing=10)
            icon = label(symbol)
            icon.set_size_request(20, -1)
            row.pack_start(icon, False, False, 0)
            row.pack_start(label(title), True, True, 0)
            row.pack_end(label(key, "muted"), False, False, 0)
            toggle.add(row)
            toggle.get_style_context().add_class("tool")
            toggle.set_tooltip_text(f"{title} ({key})")
            self.tool_handlers[tool] = toggle.connect("clicked", lambda widget, value=tool: self.set_tool(value))
            self.tool_buttons[tool] = toggle
            sidebar.pack_start(toggle, False, False, 0)
        sidebar.pack_start(Gtk.Separator(), False, False, 12)
        color_heading = Gtk.Box()
        color_heading.pack_start(label("颜色", "section"), True, True, 0)
        color_heading.pack_end(button("＋", self.custom_color, "自定义颜色", "custom-color"), False, False, 0)
        sidebar.pack_start(color_heading, False, False, 4)
        colors = Gtk.Grid(column_spacing=6, row_spacing=6)
        self.swatches = {}
        for index, color in enumerate(COLORS):
            swatch = Gtk.Button()
            swatch.set_size_request(28, 28)
            css = Gtk.CssProvider()
            css.load_from_data(f"button {{background: {color}; min-width: 20px; min-height: 20px; padding: 0; border: 2px solid #657083; border-radius: 14px;}}".encode())
            swatch.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
            swatch.connect("clicked", lambda _, value=color: self.set_color(value))
            swatch.set_tooltip_text(color)
            self.swatches[color] = swatch
            colors.attach(swatch, index % 4, index // 4, 1, 1)
        sidebar.pack_start(colors, False, False, 4)
        sidebar.pack_start(label("粗细 / 打码强度", "section"), False, False, 4)
        self.width = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 24, 1)
        self.width.set_digits(0)
        self.width.set_round_digits(0)
        self.width.set_value_pos(Gtk.PositionType.RIGHT)
        self.width.set_value(4)
        self.width.set_tooltip_text("像素单位；打码工具中控制马赛克方块大小")
        sidebar.pack_start(self.width, False, False, 0)
        sidebar.pack_start(label("文字大小", "section"), False, False, 4)
        self.font_size = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 144, 2)
        self.font_size.set_digits(0)
        self.font_size.set_round_digits(0)
        self.font_size.set_value_pos(Gtk.PositionType.RIGHT)
        self.font_size.set_value(28)
        sidebar.pack_start(self.font_size, False, False, 0)
        sidebar.pack_end(button("设置", self.preferences), False, False, 4)

        workspace = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.pack_start(workspace, True, True, 0)
        bar = Gtk.Box(spacing=6)
        bar.get_style_context().add_class("toolbar")
        workspace.pack_start(bar, False, False, 0)
        self.undo_button = button("↶", self.undo, "撤销  Ctrl+Z")
        self.redo_button = button("↷", self.redo, "重做  Ctrl+Shift+Z")
        bar.pack_start(self.undo_button, False, False, 0)
        bar.pack_start(self.redo_button, False, False, 0)
        bar.pack_start(button("删除标记", self.delete_selected, "先选择标记，然后按 Delete"), False, False, 4)
        self.doc_label = label("准备好，留下重点。", "muted")
        self.doc_label.set_ellipsize(3)
        bar.pack_start(self.doc_label, True, True, 8)
        bar.pack_end(button("适应", self.fit, "适应窗口  Ctrl+0"), False, False, 0)
        bar.pack_end(button("＋", lambda: self.canvas.set_zoom(self.canvas.zoom * 1.2)), False, False, 0)
        self.zoom_label = label("100%", "muted")
        self.zoom_label.set_size_request(48, -1)
        bar.pack_end(self.zoom_label, False, False, 0)
        bar.pack_end(button("−", lambda: self.canvas.set_zoom(self.canvas.zoom / 1.2)), False, False, 0)
        self.stack = Gtk.Stack()
        workspace.pack_start(self.stack, True, True, 0)
        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                        halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        empty.pack_start(label("z /", "hero", .5), False, False, 0)
        empty.pack_start(label("把重点，标出来。", "hero", .5), False, False, 0)
        empty.pack_start(label("一张截图，一点标记。让想法清晰可见。", "muted", .5), False, False, 0)
        actions = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        actions.pack_start(button("截取屏幕", app.capture, css="suggested-action"), False, False, 0)
        actions.pack_start(button("导入图片", self.open_file), False, False, 0)
        actions.pack_start(button("从剪贴板粘贴", self.paste), False, False, 0)
        empty.pack_start(actions, False, False, 10)
        empty.pack_start(label("也可以把图片拖到这里", "hint", .5), False, False, 0)
        empty.pack_start(label("WAYLAND  ·  系统截图", "badge", .5), False, False, 14)
        self.stack.add_named(empty, "empty")
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.canvas = Canvas(self)
        self.scroller.add(self.canvas)
        self.stack.add_named(self.scroller, "canvas")
        statusbar = Gtk.Box(spacing=20)
        statusbar.get_style_context().add_class("statusbar")
        self.status = label("就绪 · 使用系统截图，或按 Ctrl+V 粘贴图片")
        self.dimensions = label("")
        statusbar.pack_start(self.status, True, True, 0)
        statusbar.pack_end(self.dimensions, False, False, 0)
        root.pack_end(statusbar, False, False, 0)
        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drag_dest_add_uri_targets()
        self.connect("drag-data-received", self.drop)
        self.set_tool("arrow")
        self.set_color(COLORS[0])
        self.changed()
        self.show_all()

    def set_tool(self, tool):
        self.tool = tool
        self.canvas.reset()
        for name, widget in self.tool_buttons.items():
            widget.handler_block(self.tool_handlers[name])
            widget.set_active(name == tool)
            widget.handler_unblock(self.tool_handlers[name])
        tips = {"select": "点击选择，拖动移动 · Delete 删除 · 双击编辑文字",
                "text": "点击图片添加文字", "number": "点击图片添加连续数字",
                "mosaic": "拖动覆盖区域 · 粗细控制打码强度",
                "ellipse": "拖动画圆形 · 按住 Shift 画正圆",
                "rectangle": "拖动画矩形 · 按住 Shift 画正方形"}
        self.status.set_text(tips.get(tool, "在图片上拖动绘制 · Ctrl+Z 撤销"))

    def set_color(self, value):
        self.color = value
        for color, swatch in self.swatches.items():
            swatch.set_label("✓" if color == value else "")

    def custom_color(self):
        dialog = Gtk.ColorChooserDialog(title="选择标记颜色", transient_for=self, modal=True)
        dialog.set_use_alpha(False)
        rgba = Gdk.RGBA()
        rgba.parse(self.color)
        dialog.set_rgba(rgba)
        if dialog.run() == Gtk.ResponseType.OK:
            rgba = dialog.get_rgba()
            self.set_color("#{:02x}{:02x}{:02x}".format(round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255)))
        dialog.destroy()

    def new_mark(self, tool, points, text=""):
        return Mark(tool, tuple(points), self.color, self.width.get_value(), text,
                    self.document.next_number, round(self.font_size.get_value()))

    def changed(self):
        doc = self.document
        self.copy_button.set_sensitive(doc is not None)
        self.undo_button.set_sensitive(bool(doc and doc.can_undo))
        self.redo_button.set_sensitive(bool(doc and doc.can_redo))
        if doc:
            self.set_title(f"{'● ' if doc.dirty else ''}{doc.name} — zprint")
            self.doc_label.set_text(f"{doc.name}  ·  {len(doc.marks)} 个标记")
            self.dimensions.set_text(f"{doc.width} × {doc.height} px")
        self.canvas.queue_draw()

    def load(self, pixbuf, name):
        self._paste_serial += 1
        self.document = Document(pixbuf, name)
        self.canvas.reset()
        self.stack.set_visible_child_name("canvas")
        self.changed()
        GLib.idle_add(self.fit)
        self.status.set_text("图片已载入 · 选择左侧工具开始标记")

    def fit(self):
        if self.document:
            w = max(100, self.scroller.get_allocated_width() - 66)
            h = max(100, self.scroller.get_allocated_height() - 66)
            self.canvas.set_zoom(min(1, w / self.document.width, h / self.document.height))
        return GLib.SOURCE_REMOVE

    def message(self, title, detail, error=False):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                                   message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
                                   buttons=Gtk.ButtonsType.CLOSE, text=title)
        dialog.format_secondary_text(detail)
        dialog.run()
        dialog.destroy()

    def confirm_replace(self):
        if not self.document or not self.document.dirty:
            return True
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   text="标记还没有导出", secondary_text="导出图片后再继续，或放弃当前标记。")
        dialog.add_buttons("取消", Gtk.ResponseType.CANCEL, "放弃标记", Gtk.ResponseType.REJECT,
                           "先导出", Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.ACCEPT:
            return self.export()
        return response == Gtk.ResponseType.REJECT

    def close_requested(self, *_):
        return not self.confirm_replace()

    def open_file(self):
        chooser = Gtk.FileChooserNative.new("导入图片", self, Gtk.FileChooserAction.OPEN, "打开", "取消")
        image_filter = Gtk.FileFilter()
        image_filter.set_name("图片")
        image_filter.add_pixbuf_formats()
        chooser.add_filter(image_filter)
        if chooser.run() == Gtk.ResponseType.ACCEPT:
            self.load_file(chooser.get_filename())
        chooser.destroy()

    def load_file(self, path):
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path).apply_embedded_orientation()
        except GLib.Error as error:
            self.message("无法读取图片", str(error), True)
            return False
        if self.confirm_replace():
            self.load(pixbuf, Path(path).name)
            return True
        return False

    def drop(self, widget, context, x, y, data, info, time):
        uris = data.get_uris() or []
        path = Gio.File.new_for_uri(uris[0]).get_path() if uris else None
        success = self.load_file(path) if path else False
        Gtk.drag_finish(context, success, False, time)

    def paste(self):
        self.present()
        # Wayland delivers clipboard offers to the focused surface.
        self._paste_serial += 1
        serial = self._paste_serial

        def read():
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).request_image(received, None)
            return GLib.SOURCE_REMOVE

        def received(clipboard, pixbuf, data):
            if serial != self._paste_serial or not self.get_visible():
                return
            if pixbuf is None:
                self.message("剪贴板中没有可读取的图片", "先用 PrintScreen 截图，再回到 zprint 按 Ctrl+V；也可以直接点击“截图”。")
            else:
                self.load(pixbuf, "剪贴板图片")
        GLib.timeout_add(200, read)

    def copy(self):
        if not self.document:
            return
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_image(self.document.pixbuf())
        clipboard.store()
        self.status.set_text("已复制标记后的图片 · 可以直接粘贴到聊天或文档")

    def export(self):
        if not self.document:
            return False
        chooser = Gtk.FileChooserNative.new("导出图片", self, Gtk.FileChooserAction.SAVE, "导出", "取消")
        chooser.set_do_overwrite_confirmation(True)
        stem = Path(self.document.name).stem
        chooser.set_current_name(f"{stem}-标记.png")
        for title, patterns in [("PNG 图片", ["*.png"]), ("JPEG 图片", ["*.jpg", "*.jpeg"])]:
            file_filter = Gtk.FileFilter()
            file_filter.set_name(title)
            for pattern in patterns:
                file_filter.add_pattern(pattern)
            chooser.add_filter(file_filter)
        success = False
        if chooser.run() == Gtk.ResponseType.ACCEPT:
            path = chooser.get_filename()
            if not Path(path).suffix:
                extension = ".jpg" if chooser.get_filter().get_name() == "JPEG 图片" else ".png"
                path += extension
                # The file chooser confirmed the name before extension insertion.
                if Path(path).exists():
                    confirm = Gtk.MessageDialog(transient_for=self, modal=True, text="覆盖已有文件？",
                                                secondary_text=path, buttons=Gtk.ButtonsType.YES_NO)
                    overwrite = confirm.run() == Gtk.ResponseType.YES
                    confirm.destroy()
                    if not overwrite:
                        chooser.destroy()
                        return False
            try:
                self.document.export(path)
                self.changed()
                self.status.set_text(f"已导出：{path}")
                success = True
            except (OSError, GLib.Error, ValueError, cairo.Error) as error:
                self.message("导出失败", str(error), True)
        chooser.destroy()
        return success

    def undo(self):
        if self.document:
            self.canvas.reset()
            self.document.undo()
            self.changed()

    def redo(self):
        if self.document:
            self.canvas.reset()
            self.document.redo()
            self.changed()

    def delete_selected(self):
        selected = self.canvas.selected
        if self.document and selected is not None:
            self.document.commit(m for i, m in enumerate(self.document.marks) if i != selected)
            self.canvas.reset()
            self.changed()

    def edit_text(self, point, index=None):
        dialog = Gtk.Dialog(title="编辑文字" if index is not None else "添加文字", transient_for=self, modal=True)
        dialog.add_buttons("取消", Gtk.ResponseType.CANCEL, "完成", Gtk.ResponseType.OK)
        dialog.set_default_size(420, 230)
        dialog.set_default_response(Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_border_width(16)
        content.pack_start(label("输入文字，支持中文和多行", "muted"), False, False, 0)
        text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        text.set_left_margin(10)
        text.set_right_margin(10)
        text.set_top_margin(10)
        scroll = Gtk.ScrolledWindow()
        scroll.add(text)
        content.pack_start(scroll, True, True, 0)
        buffer = text.get_buffer()
        if index is not None:
            buffer.set_text(self.document.marks[index].text)
        dialog.show_all()
        text.grab_focus()
        if dialog.run() == Gtk.ResponseType.OK:
            value = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
            if value.strip():
                if index is None:
                    self.document.add(self.new_mark("text", (point,), value))
                else:
                    marks = list(self.document.marks)
                    marks[index] = replace(marks[index], text=value)
                    self.document.commit(marks)
                self.changed()
        dialog.destroy()

    def key_press(self, widget, event):
        focus = self.get_focus()
        if isinstance(focus, (Gtk.Entry, Gtk.TextView)):
            return False
        key = Gdk.keyval_name(event.keyval).lower()
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl:
            callbacks = {"o": self.open_file, "v": self.paste, "c": self.copy, "s": self.export,
                         "z": self.redo if shift else self.undo, "y": self.redo, "0": self.fit,
                         "n": self.get_application().capture}
            if key in callbacks:
                callbacks[key]()
                return True
        elif key in ("delete", "backspace"):
            self.delete_selected()
            return True
        elif key == "escape":
            self.canvas.reset()
            return True
        elif key == "f1":
            self.help()
            return True
        elif not event.state & (Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.SUPER_MASK):
            for tool, _, _, shortcut in TOOLS:
                if key == shortcut.lower():
                    self.set_tool(tool)
                    return True
        return False

    def preferences(self, page="shortcuts"):
        dialog = Preferences(self, page=page)
        dialog.run()
        dialog.destroy()

    def help(self):
        self.preferences(page="help")


class Zprint(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.zprint.Zprint", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.request = None
        self.capture_windows = []
        self.shortcuts_ready = False

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        css = Gtk.CssProvider()
        css.load_from_path(str(Path(__file__).with_name("style.css")))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.Window.set_default_icon_name("zprint")

    def editor(self, new=False):
        windows = self.get_windows()
        window = None if new else next((w for w in windows if isinstance(w, Editor)), None)
        return window or Editor(self)

    def do_activate(self):
        self.ensure_shortcuts()
        self.editor().present()

    def ensure_shortcuts(self):
        if not self.shortcuts_ready and launcher_path() == Path("/usr/bin/zprint"):
            install_shortcuts(launcher_command())
            self.shortcuts_ready = True

    def do_command_line(self, command):
        args = command.get_arguments()[1:]
        if "--help" in args or "-h" in args:
            command.do_print_literal(command, "用法：zprint [--capture | --clipboard | 图片路径]\n")
            return 0
        self.ensure_shortcuts()
        if "--capture" in args:
            self.capture()
        elif "--clipboard" in args:
            window = self.editor()
            window.present()
            window.paste()
        elif args:
            for arg in args:
                if arg.startswith("-"):
                    command.do_printerr_literal(command, f"未知选项：{arg}\n")
                    return 2
                file = command.create_file_for_arg(arg)
                path = file.get_path()
                window = self.editor(new=True)
                window.present()
                if path:
                    window.load_file(path)
                else:
                    window.message("无法打开此图片", "请先将图片保存到本地。", True)
        else:
            self.activate()
        return 0

    def capture(self):
        if self.request is not None:
            return
        self.hold()
        self.capture_windows = [w for w in self.get_windows() if w.get_visible()]
        for window in self.capture_windows:
            window.hide()
        self.request = ScreenshotRequest(self.capture_finished)
        GLib.timeout_add(250, self.start_capture)

    def start_capture(self):
        if self.request:
            self.request.start()
        return GLib.SOURCE_REMOVE

    def capture_finished(self, uri, error):
        self.request = None
        for window in self.capture_windows:
            window.show()
        self.capture_windows = []
        if error:
            window = self.editor()
            window.present()
            window.message("无法启动系统截图", error + "\n\n可以先按 PrintScreen，再回到 zprint 粘贴剪贴板图片。", True)
        elif uri:
            window = self.editor()
            window.present()
            try:
                file = Gio.File.new_for_uri(uri)
                stream = file.read(None)
                try:
                    screenshot = GdkPixbuf.Pixbuf.new_from_stream(stream, None)
                finally:
                    stream.close(None)
            except GLib.Error as load_error:
                window.message("无法加载系统截图", str(load_error), True)
            else:
                name = "截图 " + datetime.now().strftime("%Y-%m-%d %H-%M-%S")
                # Load the portal's exact result immediately. Once focused, prefer
                # the clipboard only when it matches this capture, never an old image.
                window.load(screenshot, name)
                document = window.document

                def received(clipboard, pixbuf, data):
                    if window.document is document and not document.marks and pixbuf and identical_image(pixbuf, screenshot):
                        window.load(pixbuf, name)
                        window.status.set_text("已读取系统截图的剪贴板图片 · 开始标记吧")

                def read_clipboard():
                    if window.get_visible():
                        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).request_image(received, None)
                    return GLib.SOURCE_REMOVE
                GLib.timeout_add(250, read_clipboard)
        self.release()


def main():
    app = Zprint()
    sys.exit(app.run(sys.argv))
