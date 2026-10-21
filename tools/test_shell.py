#!/usr/bin/python3
"""Run the real extension and app in a separate headless GNOME 46 session.

Usage: /usr/bin/python3 tools/test_shell.py
No Eval, user settings, user display, or installed extension is used.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import sys
from contextlib import nullcontext

ROOT = Path(__file__).resolve().parent.parent

if "--isolated" not in sys.argv:
    with tempfile.TemporaryDirectory(prefix="zprint-shell-test-", ignore_cleanup_errors=True) as folder:
        isolated = dict(os.environ, XDG_DATA_HOME=folder + "/data", XDG_CONFIG_HOME=folder + "/config",
                        XDG_CACHE_HOME=folder + "/cache", XDG_RUNTIME_DIR=folder + "/run",
                        GSETTINGS_BACKEND="keyfile", GNOME_SHELL_SESSION_MODE="user",
                        XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="GNOME",
                        WAYLAND_DISPLAY="wayland-zprint-test", GTK_USE_PORTAL="0", GTK_IM_MODULE="simple",
                        NO_AT_BRIDGE="1", GIO_USE_VFS="local", GDK_BACKEND="wayland")
        for key in ("DISPLAY", "SESSION_MANAGER", "GNOME_SETUP_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
            isolated.pop(key, None)
        bus_config = Path(folder) / "bus.conf"
        bus_config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen>'
                              '<policy context="default"><allow send_destination="*" eavesdrop="true"/>'
                              '<allow eavesdrop="true"/><allow own="*"/></policy></busconfig>')
        log = ROOT / "dist/shell-session.log"
        log.parent.mkdir(exist_ok=True)
        with log.open("w") as stream:
            result = subprocess.run(["dbus-run-session", "--config-file", str(bus_config), "--", "/usr/bin/python3", __file__, "--isolated", folder],
                                    env=isolated, stdout=stream, stderr=subprocess.STDOUT)
        print(log.read_text()[-4000:])
        sys.exit(result.returncode)

with nullcontext(sys.argv[2]) as folder:
    root = Path(folder)
    env = dict(os.environ)
    for key in ("DISPLAY", "SESSION_MANAGER", "GNOME_SETUP_DISPLAY"):
        env.pop(key, None)
    env.update(XDG_DATA_HOME=str(root / "data"), XDG_CONFIG_HOME=str(root / "config"),
               XDG_CACHE_HOME=str(root / "cache"), XDG_RUNTIME_DIR=str(root / "run"),
               GSETTINGS_BACKEND="keyfile", XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="GNOME",
               WAYLAND_DISPLAY="wayland-zprint-test", LIBGL_ALWAYS_SOFTWARE="1")
    (root / "run").mkdir(mode=0o700)
    (root / "config").mkdir()
    (root / "pictures").mkdir()
    (root / "config/user-dirs.dirs").write_text(f'XDG_PICTURES_DIR="{root}/pictures"\n')
    extension = root / "data/gnome-shell/extensions/zprint@zhou411X"
    shutil.copytree(ROOT / "gnome-extension", extension)
    (extension / "extension.js").rename(extension / "implementation.js")
    script = r'''
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import Clutter from 'gi://Clutter';
import GdkPixbuf from 'gi://GdkPixbuf';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import Zprint from './implementation.js';
const output = OUTPUT;
const repo = REPO;
const probe = PROBE;
function write(value) { GLib.file_set_contents(output, JSON.stringify(value)); }
export default class TestExtension extends Zprint {
    _launch(token) {
        this._child = Gio.Subprocess.new(['/usr/bin/python3', `${repo}/tools/shell_probe.py`, probe,
            '--shell-capture', token], Gio.SubprocessFlags.NONE);
    }
    enable() {
        this._originalSave = Main.screenshotUI._saveScreenshot;
        this._originalOpen = Main.screenshotUI.open;
        super.enable();
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 2500, () => {
            this.run().catch(e => write({error: e.message, stack: e.stack}));
            return GLib.SOURCE_REMOVE;
        });
    }
    async pause(ms) {
        await new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
            resolve(); return GLib.SOURCE_REMOVE;
        }));
    }
    async run() {
        Main.overview.hide();
        this._fixture = Gio.Subprocess.new(['/usr/bin/python3', '-c', `
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
w = Gtk.Window(title='zprint test desktop')
w.set_default_size(900, 500)
area = Gtk.DrawingArea()
def draw(widget, c):
    c.set_source_rgb(.94,.96,.98); c.paint()
    c.set_source_rgb(.12,.18,.25); c.rectangle(0,0,900,100); c.fill()
    c.set_source_rgb(.1,.35,.3); c.select_font_face('Sans',0,1); c.set_font_size(30)
    c.move_to(220,160); c.show_text('Capture. Mark. Share.')
    for i,h in enumerate([70,100,85,140,170,125]):
        c.set_source_rgb(.3,.65,.55); c.rectangle(220+i*65,380-h,40,h); c.fill()
area.connect('draw',draw); w.add(area); w.show_all(); Gtk.main()
`], Gio.SubprocessFlags.NONE);
        await this.pause(800);
        const fixture = global.get_window_actors().map(a => a.meta_window).find(w => w.get_title() === 'zprint test desktop');
        if (!fixture)
            throw new Error('Test fixture did not map');
        fixture.move_resize_frame(true, 100, 100, 900, 500);
        await this.pause(300);
        const results = [];
        for (const image of [[300, 200, 400, 200], [40, 680, 180, 100], [0, 0, 1280, 800], 'window', 'screen']) {
            // Production geometry hook and screenshot-taken signal both run here.
            await Main.screenshotUI.open();
            let expected = image;
            if (image === 'window') {
                Main.screenshotUI._windowButton.checked = true;
                const frame = fixture.get_frame_rect();
                const selected = Main.screenshotUI._windowSelectors.flatMap(s => s.windows())
                    .find(w => w.boundingBox.x === frame.x && w.boundingBox.y === frame.y);
                if (!selected)
                    throw new Error('Fixture was not selectable');
                selected.checked = true;
                const r = fixture.get_buffer_rect();
                expected = [r.x, r.y, r.width, r.height];
            } else if (image === 'screen') {
                Main.screenshotUI._screenButton.checked = true;
                Main.screenshotUI._screenSelectors[0].checked = true;
                expected = [0, 0, 1280, 800];
            } else {
                Main.screenshotUI._selectionButton.checked = true;
                const area = Main.screenshotUI._areaSelector;
                [area._startX, area._startY] = image;
                area._lastX = image[0] + image[2] - 1;
                area._lastY = image[1] + image[3] - 1;
                area._updateSelectionRect();
            }
            Main.screenshotUI._onCaptureButtonClicked();
            await this.pause(2500);
            const c = this._capture;
            if (JSON.stringify(c?.image) !== JSON.stringify(expected))
                throw new Error(`Capture geometry expected ${expected}, got ${c?.image}`);
            const windows = global.get_window_actors().map(a => a.meta_window)
                .filter(w => w.get_title()?.startsWith(`zprint-overlay:${c?.token}:`));
            if (windows.length !== 2)
                throw new Error(`Expected image and toolbar, found ${windows.length}; capture=${JSON.stringify(c)}; pending=${JSON.stringify(this._pending)}; windows=${global.get_window_actors().map(a => a.meta_window.get_title())}`);
            for (const window of windows) {
                const role = window.get_title().split(':').at(-1);
                const r = window.get_frame_rect();
                const actual = [r.x, r.y, r.width, r.height];
                if (JSON.stringify(actual) !== JSON.stringify(c[role]))
                    throw new Error(`${role} expected ${c[role]}, got ${actual}`);
            }
            results.push({image: c.image, toolbar: c.toolbar});
            if (results.length === 1) {
                const stream = Gio.File.new_for_path(SCREENSHOT).replace(null, false, Gio.FileCreateFlags.NONE, null);
                await new Shell.Screenshot().screenshot(false, stream);
                stream.close(null);
                await Main.screenshotUI.open();
                if (windows.some(w => !w.minimized))
                    throw new Error('Old overlay remained visible during screenshot');
                Main.screenshotUI.close(true);
                await this.pause(200);
                if (windows.some(w => w.minimized))
                    throw new Error('Cancel did not restore previous overlay');
                await this.checkInput();
            }
        }
        const custom = await this.checkCustomSelection();
        this.startCustom();
        await this.waitFor(() => this._selectionSession?.selector?.visible, 'Disable test selector did not open');
        super.disable();
        await this.waitFor(() => !this._selectionSession && Main.modalCount === 0, 'Disable leaked a modal selection');
        await this.key(Clutter.KEY_Print);
        await this.waitFor(() => Main.screenshotUI.visible, 'Disable did not restore system PrintScreen');
        Main.screenshotUI.close(true);
        custom.push('Disable during selection releases grab; system PrintScreen unaffected');
        if (Main.screenshotUI._saveScreenshot !== this._originalSave || Main.screenshotUI.open !== this._originalOpen)
            throw new Error('Disable did not restore screenshot methods');
        super.enable();
        if (this.GetCapture('invalid') !== '')
            throw new Error('Enable retained stale capture');
        write({passed: results.length + 3 + custom.length, results, custom,
            cancellation: 'passed', disableEnable: 'passed',
            input: '8 tools, arrow drag, undo, redo, finish; portal errors before/after capture passed'});
    }
    state() {
        const [, data] = GLib.file_get_contents(probe);
        return JSON.parse(new TextDecoder().decode(data));
    }
    async waitFor(predicate, message) {
        for (let i = 0; i < 100; i++) {
            if (predicate())
                return;
            await this.pause(50);
        }
        throw new Error(message);
    }
    async key(symbol) {
        this._keyboard ??= Clutter.get_default_backend().get_default_seat()
            .create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
        this._keyboard.notify_keyval(GLib.get_monotonic_time(), symbol, Clutter.KeyState.PRESSED);
        await this.pause(60);
        this._keyboard.notify_keyval(GLib.get_monotonic_time(), symbol, Clutter.KeyState.RELEASED);
        await this.pause(120);
    }
    async drag(from, to, preview = false) {
        this._pointer.notify_absolute_motion(GLib.get_monotonic_time(), ...from);
        await this.pause(80);
        this._pointer.notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_PRIMARY, Clutter.ButtonState.PRESSED);
        await this.pause(80);
        this._pointer.notify_absolute_motion(GLib.get_monotonic_time(), ...to);
        await this.pause(100);
        if (preview) {
            const stream = Gio.File.new_for_path(SELECTION_PREVIEW).replace(null, false, Gio.FileCreateFlags.NONE, null);
            await new Shell.Screenshot().screenshot(false, stream);
            stream.close(null);
        }
        this._pointer.notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_PRIMARY, Clutter.ButtonState.RELEASED);
    }
    async checkCustomSelection() {
        const results = [];
        const maps = this.state().editorMaps;
        let pixels = null;
        let oldFile = null;
        const systemToken = this._capture.token;
        await this.key(Clutter.KEY_Print);
        await this.waitFor(() => Main.screenshotUI.visible, 'System PrintScreen was intercepted');
        Main.screenshotUI.close(true);
        await this.pause(200);
        results.push('System PrintScreen unchanged');
        this.startCustom();
        await this.waitFor(() => this._selectionSession?.selector?.visible, 'Initial cancel selector did not open');
        await this.key(Clutter.KEY_Escape);
        await this.waitFor(() => !this._selectionSession, 'Initial cancellation leaked session');
        if (this._capture?.token !== systemToken)
            throw new Error('Cancelling first custom selection invalidated the previous system capture');
        results.push('Cancel preserves previous system capture');
        for (const mode of ['app-shortcut', 'reverse-drag']) {
            const previous = this._capture.token;
            this.startCustom();
            await this.waitFor(() => this._selectionSession?.selector?.visible, 'Custom selector did not open');
            if (Main.screenshotUI.visible)
                throw new Error('Custom capture opened system screenshot UI');
            const forward = mode === 'app-shortcut';
            await this.drag(forward ? [300, 200] : [699, 399], forward ? [699, 399] : [300, 200], forward);
            await this.waitFor(() => this._capture?.token !== previous && this.state().token === this._capture?.token,
                'Drag release did not open annotation toolbar');
            if (JSON.stringify(this._capture.image) !== '[300,200,400,200]')
                throw new Error(`Wrong custom selection geometry: ${this._capture.image}`);
            if (this.state().editorMaps !== maps || this.state().errorDialog)
                throw new Error(`Full editor or error dialog flashed during ${mode}: maps=${maps}, state=${JSON.stringify(this.state())}`);
            const file = Gio.File.new_for_uri(this._capture.uri);
            const pixbuf = GdkPixbuf.Pixbuf.new_from_file(file.get_path());
            if (pixbuf.width !== 400 || pixbuf.height !== 200)
                throw new Error('Custom image dimensions do not match selection');
            const digest = GLib.compute_checksum_for_bytes(GLib.ChecksumType.SHA256, pixbuf.read_pixel_bytes());
            if (pixels && pixels !== digest)
                throw new Error('Repeated screenshot captured old annotations or overlay');
            if (oldFile?.query_exists(null))
                throw new Error('Previous temporary capture was not removed');
            pixels = digest;
            oldFile = file;
            await this.click(...this.state().buttons.rectangle);
            await this.drag([330, 230], [440, 300]);
            await this.waitFor(() => this.state().marks[0] === 'rectangle', 'Custom screenshot was not editable');
            results.push(`${mode}: release-to-annotate, no editor flash`);
        }
        const previous = this._capture.token;
        for (const cancel of ['Escape', 'right-click']) {
            this.startCustom();
            await this.waitFor(() => this._selectionSession?.selector?.visible, 'Cancel selector did not open');
            if (cancel === 'Escape')
                await this.key(Clutter.KEY_Escape);
            else {
                this._pointer.notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_SECONDARY, Clutter.ButtonState.PRESSED);
                await this.pause(60);
                this._pointer.notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_SECONDARY, Clutter.ButtonState.RELEASED);
            }
            await this.waitFor(() => !this._selectionSession && this.state().visible, 'Cancellation leaked selection session');
            if (this._capture.token !== previous || this.state().marks.length !== 1 || Main.modalCount !== 0)
                throw new Error('Cancel lost annotations or left modal grab');
            results.push(`${cancel}: previous annotations preserved`);
        }
        this.startCustom();
        await this.waitFor(() => this._selectionSession?.selector?.visible, 'Tiny selection test did not open');
        await this.click(400, 300);
        if (!this._selectionSession?.selector?.visible)
            throw new Error('Click without drag captured a pixel');
        await this.key(Clutter.KEY_Escape);
        await this.waitFor(() => !this._selectionSession, 'Tiny selection cancel leaked session');
        results.push('Click without drag stays in selection mode');
        const cached = Gio.File.new_for_uri(this._capture.uri);
        await this.click(...this.state().buttons.finish);
        await this.waitFor(() => !this.state().visible, 'Finish did not dismiss custom screenshot');
        if (cached.query_exists(null))
            throw new Error('Finished capture left its temporary file');
        results.push('Pixel-accurate repeated capture excludes annotations; temporary files cleaned');
        return results;
    }
    startCustom() {
        Gio.Subprocess.new(['/usr/bin/python3', `${repo}/zprint`, '--capture'], Gio.SubprocessFlags.NONE);
    }
    async click(x, y) {
        this._pointer.notify_absolute_motion(GLib.get_monotonic_time(), x, y);
        await this.pause(80);
        this._pointer.notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_PRIMARY, Clutter.ButtonState.PRESSED);
        await this.pause(60);
        this._pointer.notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_PRIMARY, Clutter.ButtonState.RELEASED);
        await this.pause(180);
    }
    async checkInput() {
        // Virtual input is confined to this headless compositor, never the user session.
        this._pointer = Clutter.get_default_backend().get_default_seat()
            .create_virtual_device(Clutter.InputDeviceType.POINTER_DEVICE);
        let state = this.state();
        if (state.errorGrab || state.grab || state.errorDialog)
            throw new Error(`Portal failure left a dialog/grab: ${JSON.stringify(state)}`);
        // Restore toolbar focus after cancelling the second screenshot.
        await this.click(...state.buttons.arrow);
        for (const tool of ['select', 'pen', 'text', 'rectangle', 'ellipse', 'mosaic', 'number', 'arrow']) {
            await this.click(...state.buttons[tool]);
            if (this.state().tool !== tool)
                throw new Error(`Pointer click did not select ${tool}: ${JSON.stringify(this.state())}; ` +
                    `pointer=${global.get_pointer()}; modal=${Main.modalCount}; focus=${global.display.focus_window?.get_title()}; ` +
                    `pick=${global.stage.get_actor_at_pos(Clutter.PickMode.REACTIVE, ...state.buttons[tool])}; ` +
                    `windows=${JSON.stringify(global.get_window_actors().map(a => {
                        const w = a.meta_window, r = w.get_frame_rect();
                        return [w.get_title(), r.x, r.y, r.width, r.height, w.minimized];
                    }))}`);
        }
        const [x, y] = this._capture.image;
        this._pointer.notify_absolute_motion(GLib.get_monotonic_time(), x + 30, y + 30);
        await this.pause(80);
        this._pointer.notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_PRIMARY, Clutter.ButtonState.PRESSED);
        await this.pause(80);
        this._pointer.notify_absolute_motion(GLib.get_monotonic_time(), x + 140, y + 100);
        await this.pause(80);
        this._pointer.notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_PRIMARY, Clutter.ButtonState.RELEASED);
        await this.pause(200);
        if (JSON.stringify(this.state().marks) !== '["arrow"]')
            throw new Error('Pointer drag did not draw an arrow');
        await this.click(...state.buttons.undo);
        if (this.state().marks.length !== 0)
            throw new Error('Undo click failed');
        await this.click(...state.buttons.redo);
        if (this.state().marks.length !== 1)
            throw new Error('Redo click failed');
        await this.click(...state.buttons.finish);
        if (this.state().visible)
            throw new Error('Finish click did not dismiss overlay');
    }
}
'''
    artifact = ROOT / "dist/shell-toolbar-preview.png"
    artifact.parent.mkdir(exist_ok=True)
    script = script.replace("OUTPUT", json.dumps(str(root / "result.json")))
    script = script.replace("REPO", json.dumps(str(ROOT)))
    script = script.replace("PROBE", json.dumps(str(root / "probe.json")))
    script = script.replace("SCREENSHOT", json.dumps(str(artifact)))
    script = script.replace("SELECTION_PREVIEW", json.dumps(str(ROOT / "dist/custom-selection-preview.png")))
    (extension / "extension.js").write_text(script)
    for schema, key, value in [("org.gnome.shell", "enabled-extensions", "['zprint@zhou411X']"),
                               ("org.gnome.shell", "disable-user-extensions", "false"),
                               ("org.gnome.shell", "welcome-dialog-last-shown-version", "'46.0'")]:
        subprocess.run(["gsettings", "set", schema, key, value], env=env, check=True)
    log = ROOT / "dist/shell-test.log"
    with log.open("w") as stream:
        process = subprocess.Popen(["gnome-shell", "--mode", "user", "--headless", "--virtual-monitor", "1280x800",
                                    "--wayland-display", "wayland-zprint-test", "--no-x11"],
                                   env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            for _ in range(200):
                if (root / "result.json").exists() or process.poll() is not None:
                    break
                time.sleep(.3)
            if not (root / "result.json").exists():
                raise RuntimeError(f"Shell did not finish; see {log}")
            result = json.loads((root / "result.json").read_text())
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if "error" in result:
                raise RuntimeError(f"Shell test failed; see {log}")
        finally:
            # Terminate only this isolated session's process group.
            import signal
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
