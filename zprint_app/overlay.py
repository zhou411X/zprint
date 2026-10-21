"""Two native Wayland surfaces, positioned by the GNOME Shell companion."""

from datetime import datetime
from gi.repository import Gdk, Gtk

from .app import Canvas, Editor, COLORS, TOOLS, button, label
from .model import Document
from . import shell_bridge


class OverlayEditor(Editor):
    def __init__(self, app, pixbuf, capture):
        Gtk.ApplicationWindow.__init__(self, application=app)
        self.capture = capture
        self.document = Document(pixbuf, "截图 " + datetime.now().strftime("%Y-%m-%d %H-%M-%S"))
        self.tool, self.color, self._paste_serial = "arrow", COLORS[0], 0
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.connect("delete-event", self.close_requested)
        self.connect("key-press-event", self.key_press)
        self.canvas = Canvas(self)
        self.canvas.image_size = tuple(capture["image"][2:])
        self.canvas.zoom = self.canvas.image_size[0] / self.document.width
        self.canvas.set_size_request(*self.canvas.image_size)
        self.add(self.canvas)
        self.status, self.dimensions, self.doc_label, self.zoom_label = [label("") for _ in range(4)]

        self.bar_window = Gtk.ApplicationWindow(application=app, transient_for=self)
        self.bar_window.get_style_context().add_class("floating-window")
        visual = self.bar_window.get_screen().get_rgba_visual()
        if visual:
            self.bar_window.set_visual(visual)
        self.bar_window.set_decorated(False)
        self.bar_window.set_resizable(False)
        self.bar_window.set_skip_taskbar_hint(True)
        self.bar_window.set_skip_pager_hint(True)
        self.bar_window.set_title(f'zprint-overlay:{capture["token"]}:toolbar')
        self.bar_window.connect("delete-event", self.close_requested)
        self.bar_window.connect("key-press-event", self.key_press)
        self.connect("destroy", lambda *_: self.bar_window.destroy())
        bar = Gtk.Box(spacing=2)
        bar.get_style_context().add_class("floating-toolbar")
        # Allow a horizontally scrollable toolbar on unusually narrow monitors.
        self.bar_scroll = Gtk.ScrolledWindow()
        self.bar_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.bar_scroll.add(bar)
        self.bar_window.add(self.bar_scroll)
        self.tool_buttons, self.tool_handlers = {}, {}
        for tool, symbol, title, key in TOOLS:
            toggle = Gtk.ToggleButton(label=symbol)
            toggle.set_tooltip_text(f"{title} ({key})")
            self.tool_handlers[tool] = toggle.connect("clicked", lambda _, value=tool: self.set_tool(value))
            self.tool_buttons[tool] = toggle
            bar.add(toggle)
        style_button = Gtk.MenuButton(label="●")
        style_button.set_tooltip_text("颜色、粗细、打码强度、文字大小")
        bar.add(style_button)
        popover = Gtk.Popover.new(style_button)
        options = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=14)
        options.set_size_request(230, -1)
        popover.add(options)
        style_button.set_popover(popover)
        colors = Gtk.Box(spacing=4)
        self.swatches = {}
        for color in COLORS:
            swatch = button("", lambda value=color: self.set_color(value), color)
            css = Gtk.CssProvider()
            css.load_from_data(f"button {{background:{color}; min-width:20px; min-height:20px; padding:0; border-radius:12px;}}".encode())
            swatch.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
            self.swatches[color] = swatch
            colors.add(swatch)
        options.add(colors)
        options.add(button("自定义颜色…", self.custom_color))
        options.add(label("粗细 / 打码强度"))
        self.width = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 24, 1)
        self.width.set_digits(0)
        self.width.set_value(4)
        options.add(self.width)
        options.add(label("文字大小"))
        self.font_size = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 144, 2)
        self.font_size.set_digits(0)
        self.font_size.set_value(28)
        options.add(self.font_size)
        options.add(button("设置", self.preferences))
        options.show_all()
        bar.add(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self.undo_button = button("↶", self.undo, "撤销  Ctrl+Z")
        self.redo_button = button("↷", self.redo, "重做  Ctrl+Shift+Z")
        bar.add(self.undo_button)
        bar.add(self.redo_button)
        bar.add(button("↓", self.export, "导出图片  Ctrl+S"))
        bar.add(button("↗", self.expand, "在完整编辑器中打开"))
        bar.add(button("×", self.discard, "放弃标记并收起  Esc", "cancel-capture"))
        self.copy_button = button("✓", self.finish, "复制标记后的图片并收起  Enter", "suggested-action")
        bar.add(self.copy_button)
        bar.show_all()
        _, size = bar.get_preferred_size()
        try:
            self.capture = shell_bridge.prepare(capture["token"], size.width, size.height)
        except Exception:
            self.destroy()
            raise
        self.bar_scroll.set_size_request(*self.capture["toolbar"][2:])
        self.set_tool("arrow")
        self.set_color(COLORS[0])
        self.changed()

    def open(self):
        self.show_all()
        self.bar_window.show_all()
        self.present()
        self.canvas.grab_focus()

    def changed(self):
        super().changed()
        self.set_title(f'zprint-overlay:{self.capture["token"]}:image')

    def fit(self):
        return False  # Image must stay aligned with the original desktop selection.

    def finish(self):
        self.copy()
        self.discard()

    def discard(self, dismiss=True):
        self.bar_window.hide()
        self.hide()
        self.canvas.reset()
        self.document = None
        if dismiss:
            shell_bridge.dismiss(self.capture["token"])
        # Keep a hidden application window alive to serve the Wayland clipboard.

    def close_requested(self, *_):
        self.discard()
        return True

    def expand(self):
        window = self.get_application().editor()
        window.document = self.document
        window.canvas.reset()
        window.stack.set_visible_child_name("canvas")
        window.changed()
        window.show_all()
        window.fit()
        window.present()
        self.discard()

    def open_file(self):
        self.expand()
        self.get_application().editor().open_file()

    def paste(self):
        self.expand()
        self.get_application().editor().paste()

    def key_press(self, widget, event):
        key = Gdk.keyval_name(event.keyval).lower()
        if key == "escape":
            if self.canvas.draft:
                self.canvas.reset()
            else:
                self.discard()
            return True
        if key in ("return", "kp_enter"):
            self.finish()
            return True
        return super().key_press(widget, event)
