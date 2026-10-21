#!/usr/bin/python3
"""Test-only app observer for test_shell.py's isolated Wayland session."""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from zprint_app.app import Editor, Zprint
from zprint_app.overlay import OverlayEditor
from gi.repository import Gdk, GLib, Gtk


class Probe(Zprint):
    def do_startup(self):
        super().do_startup()
        self.events = []
        self.editor_maps = 0
        self.connect("window-added", lambda app, window: window.connect("map", self.mapped))
        # Reproduce the error-first ordering before the real extension launch.
        self.hold()
        self.capture_finished(None, "Test: portal closed before screenshot-taken")
        self.error_grab = Gtk.grab_get_current() is not None
        GLib.timeout_add(50, self.observe)

    def do_command_line(self, command):
        previous = self.last_shell_token
        result = super().do_command_line(command)
        for window in self.get_windows():
            if isinstance(window, OverlayEditor):
                for name, button in window.tool_buttons.items():
                    button.connect("event", self.event, name)
        # Also reproduce a late failure after the successful extension launch.
        if command.get_arguments()[1:2] == ["--shell-capture"] and self.last_shell_token != previous:
            self.capture_shell_token = previous
            self.hold()
            self.capture_finished(None, "Test: late portal failure")
        return result

    def mapped(self, window):
        if isinstance(window, Editor) and not isinstance(window, OverlayEditor):
            self.editor_maps += 1

    def event(self, widget, event, name):
        if event.type in (Gdk.EventType.BUTTON_PRESS, Gdk.EventType.BUTTON_RELEASE):
            self.events.append([name, str(event.type), event.get_button()[1], *event.get_coords()[1:]])
        return False

    def observe(self):
        state = {"errorGrab": self.error_grab, "grab": Gtk.grab_get_current() is not None,
                 "errorDialog": self.capture_error_dialog is not None, "visible": False,
                 "events": self.events[-4:], "editorMaps": self.editor_maps}
        for window in self.get_windows():
            if not isinstance(window, OverlayEditor) or not window.get_visible():
                continue
            buttons = dict(window.tool_buttons, undo=window.undo_button,
                           redo=window.redo_button, finish=window.copy_button)
            points = {}
            for name, widget in buttons.items():
                x, y = widget.translate_coordinates(window.bar_window, 0, 0)
                points[name] = [window.capture["toolbar"][0] + x + widget.get_allocated_width() / 2,
                                window.capture["toolbar"][1] + y + widget.get_allocated_height() / 2]
            state.update(visible=True, token=window.capture["token"], tool=window.tool,
                         marks=[m.tool for m in window.document.marks], buttons=points)
        temporary = OUTPUT.with_suffix(".tmp")
        temporary.write_text(json.dumps(state))
        temporary.replace(OUTPUT)
        return GLib.SOURCE_CONTINUE


if __name__ == "__main__":
    if os.environ.get("WAYLAND_DISPLAY") != "wayland-zprint-test":
        raise SystemExit("Run through tools/test_shell.py in its isolated session")
    OUTPUT = Path(sys.argv[1])
    sys.exit(Probe().run([sys.argv[0], *sys.argv[2:]]))
