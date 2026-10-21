import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import {Extension, InjectionManager} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {toolbarRect} from './geometry.js';
import {CaptureSelection} from './selection.js';

const IFACE = `<node><interface name="io.github.zprint.Shell">
  <method name="Capture"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
  <method name="CancelCapture"><arg type="s" direction="in"/></method>
  <method name="GetCapture"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
  <method name="Prepare"><arg type="s" direction="in"/><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="s" direction="out"/></method>
  <method name="Dismiss"><arg type="s" direction="in"/></method>
</interface></node>`;
const rect = r => [r.x, r.y, r.width, r.height].map(Math.round);

export default class ZprintExtension extends Extension {
    enable() {
        this._windows = new Map();
        this._capture = null;
        this._pending = null;
        this._hidden = [];
        this._saving = false;
        this._selectionSession = null;
        this._captureFile = null;
        this._injections = new InjectionManager();
        const owner = this;
        this._injections.overrideMethod(Main.screenshotUI, 'open', original =>
            async function (...args) {
                if (this.visible || this._openingCoroutineInProgress)
                    return original.apply(this, args);
                owner._hidden = [];
                for (const actor of global.get_window_actors()) {
                    const window = actor.meta_window;
                    if (window.get_gtk_application_id() === 'io.github.zprint.Zprint' &&
                        window.get_title()?.startsWith('zprint-overlay:') && !window.minimized) {
                        owner._hidden.push(window);
                        Main.wm.skipNextEffect(actor);
                        window.minimize();
                    }
                }
                try {
                    return await original.apply(this, args);
                } catch (error) {
                    owner._restore();
                    throw error;
                }
            });
        // Snapshot before close() resets the area and destroys window selectors.
        this._injections.overrideMethod(Main.screenshotUI, '_saveScreenshot', original =>
            function (...args) {
                try {
                    owner._pending = owner._geometry(this);
                } catch (error) {
                    owner._pending = null;
                    console.error(`zprint: cannot read screenshot geometry: ${error}`);
                }
                // The image/toolbar stay hidden when a new screenshot succeeds.
                const promise = original.apply(this, args);
                owner._saving = true;
                return promise.finally(() => {
                    owner._saving = false;
                    if (owner._hidden.length)
                        owner._restore(); // Saving failed (no screenshot-taken signal).
                });
            });
        this._closedId = Main.screenshotUI.connect('closed', () => {
            if (!this._saving)
                this._restore();
        });
        this._shotId = Main.screenshotUI.connect('screenshot-taken', (_ui, file) => {
            if (!this._pending)
                return;
            this._capture = {...this._pending, uri: file.get_uri(), token: GLib.uuid_string_random()};
            this._pending = null;
            this._hidden = [];
            try {
                // exec argv, not a shell command; user installation takes precedence.
                this._launch(this._capture.token);
            } catch (error) {
                Main.notifyError('zprint', `无法启动标记工具：${error.message}`);
            }
        });
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, '/io/github/zprint/Shell');
        this._createdId = global.display.connect('window-created', (_display, window) => this._watch(window));
        for (const actor of global.get_window_actors())
            this._watch(actor.meta_window);
        this._monitorsId = Main.layoutManager.connect('monitors-changed', () => {
            this._cancelSelection();
            // A stale desktop rectangle is never reused after display reconfiguration.
            this._capture = null;
            for (const window of this._windows.keys()) {
                if (window.get_title()?.startsWith('zprint-overlay:'))
                    window.minimize();
            }
        });
    }

    _restore() {
        for (const window of this._hidden) {
            if (this._windows.has(window))
                window.unminimize();
        }
        this._hidden = [];
    }

    _launch(token) {
        const user = GLib.build_filenamev([GLib.get_home_dir(), '.local/bin/zprint']);
        const executable = GLib.file_test(user, GLib.FileTest.IS_EXECUTABLE) ? user : '/usr/bin/zprint';
        Gio.Subprocess.new([executable, '--shell-capture', token], Gio.SubprocessFlags.NONE);
    }

    async CaptureAsync([requestId], invocation) {
        try {
            const capture = await this._select(requestId);
            invocation.return_value(new GLib.Variant('(s)', [capture?.uri ?? '']));
        } catch (error) {
            invocation.return_dbus_error('io.github.zprint.CaptureError', error.message);
        }
    }

    CancelCapture(requestId) {
        if (this._selectionSession?.id === requestId)
            this._cancelSelection();
    }

    _cancelSelection() {
        if (this._selectionSession) {
            this._selectionSession.cancelled = true;
            this._selectionSession.selector?.cancel();
            for (const window of this._selectionSession.hidden) {
                if (this._windows.has(window))
                    window.unminimize();
            }
            this._selectionSession.hidden = [];
        }
    }

    _releaseCaptureFile() {
        if (this._captureFile) {
            try {
                this._captureFile.delete(null);
            } catch (error) {
                console.error(`zprint: cannot remove cached capture: ${error}`);
            }
            this._captureFile = null;
        }
    }

    async _select(requestId) {
        if (this._selectionSession || Main.screenshotUI.visible || Main.sessionMode.isLocked || Main.sessionMode.isGreeter)
            throw new Error('当前无法开始截图，请先关闭其他截图界面。');
        const session = {id: requestId, cancelled: false, selector: null, hidden: []};
        this._selectionSession = session;
        let file = null;
        let succeeded = false;
        try {
            Main.overview.hide();
            Main.layoutManager.emit('system-modal-opened');
            for (const actor of global.get_window_actors()) {
                const window = actor.meta_window;
                if (window.get_gtk_application_id() === 'io.github.zprint.Zprint' && !window.minimized) {
                    session.hidden.push(window);
                    Main.wm.skipNextEffect(actor);
                    window.minimize();
                }
            }
            // Capture the frame after the hidden windows have left the stage,
            // not the previous frame's texture (which can still contain them).
            await new Promise(resolve => {
                const id = global.stage.connect('after-paint', () => {
                    global.stage.disconnect(id);
                    resolve();
                });
                global.stage.queue_redraw();
            });
            if (session.cancelled)
                return null;
            const shooter = new Shell.Screenshot();
            const [content, scale] = await shooter.screenshot_stage_to_content();
            if (session.cancelled)
                return null;
            session.selector = new CaptureSelection(content);
            const selection = await session.selector.selectAsync();
            session.selector = null;
            if (!selection || session.cancelled)
                return null;
            const geometry = this._captureGeometry(rect(selection));
            const token = GLib.uuid_string_random();
            const folder = GLib.build_filenamev([GLib.get_user_cache_dir(), 'zprint', 'captures']);
            GLib.mkdir_with_parents(folder, 0o700);
            file = Gio.File.new_for_path(GLib.build_filenamev([folder, `${token}.png`]));
            const stream = file.create(Gio.FileCreateFlags.PRIVATE, null);
            try {
                await Shell.Screenshot.composite_to_stream(content.get_texture(),
                    ...geometry.image.map(v => Math.round(v * scale)), scale, null, 0, 0, 1, stream);
            } finally {
                stream.close(null);
            }
            if (session.cancelled)
                return null;
            this._releaseCaptureFile();
            this._captureFile = file;
            this._capture = {...geometry, uri: file.get_uri(), token};
            this._launch(token);
            succeeded = true;
            return this._capture;
        } finally {
            if (!succeeded) {
                if (file && this._captureFile === file) {
                    this._captureFile = null;
                    this._capture = null;
                }
                if (file?.query_exists(null))
                    file.delete(null);
                for (const window of session.hidden) {
                    if (this._windows.has(window))
                        window.unminimize();
                }
            }
            if (this._selectionSession === session)
                this._selectionSession = null;
        }
    }

    _geometry(ui) {
        let image;
        if (ui._selectionButton.checked || ui._screenButton.checked) {
            image = ui._getSelectedGeometry(false).map(Math.round);
        } else {
            const selected = ui._windowSelectors.flatMap(s => s.windows()).find(w => w.checked);
            if (!selected)
                return null;
            // The saved window texture includes the buffer (including shadow), not just its frame.
            image = rect(selected.child._bufferRect);
        }
        return this._captureGeometry(image);
    }

    _captureGeometry(image) {
        const [x, y, w, h] = image;
        const monitors = Main.layoutManager.monitors;
        const monitor = monitors.find(m => x + w / 2 >= m.x && x + w / 2 < m.x + m.width &&
            y + h / 2 >= m.y && y + h / 2 < m.y + m.height) ?? Main.layoutManager.primaryMonitor;
        return {image, monitor: rect(monitor)};
    }

    GetCapture(key) {
        const c = this._capture;
        return c && (key === c.token || key === c.uri) ? JSON.stringify(c) : '';
    }

    Prepare(token, width, height) {
        const c = this._capture;
        if (!c || c.token !== token || width < 1 || height < 1)
            throw new Error('Screenshot expired; take a new screenshot.');
        c.toolbar = toolbarRect(c.image, c.monitor, width, height);
        for (const window of this._windows.keys())
            this._place(window);
        return JSON.stringify(c);
    }

    Dismiss(token) {
        if (this._capture?.token === token) {
            this._capture = null;
            this._releaseCaptureFile();
        }
    }

    _watch(window) {
        if (this._windows.has(window))
            return;
        const ids = [window.connect('notify::title', () => this._place(window)),
            window.connect('shown', () => this._place(window)),
            window.connect('unmanaged', () => this._unwatch(window))];
        this._windows.set(window, ids);
        this._place(window);
    }

    _unwatch(window) {
        for (const id of this._windows.get(window) ?? [])
            window.disconnect(id);
        this._windows.delete(window);
    }

    _place(window) {
        const c = this._capture;
        if (!c?.toolbar || window.get_gtk_application_id() !== 'io.github.zprint.Zprint')
            return;
        const title = window.get_title();
        const role = ['image', 'toolbar'].find(r => title === `zprint-overlay:${c.token}:${r}`);
        if (!role)
            return;
        window.unmaximize(Meta.MaximizeFlags.BOTH);
        window.make_above();
        window.move_resize_frame(true, ...c[role]);
    }

    disable() {
        this._cancelSelection();
        this._releaseCaptureFile();
        this._injections?.clear();
        if (this._shotId)
            Main.screenshotUI.disconnect(this._shotId);
        if (this._closedId)
            Main.screenshotUI.disconnect(this._closedId);
        if (this._createdId)
            global.display.disconnect(this._createdId);
        if (this._monitorsId)
            Main.layoutManager.disconnect(this._monitorsId);
        for (const window of [...this._windows.keys()]) {
            if (window.get_title()?.startsWith('zprint-overlay:')) {
                window.unmake_above();
                window.minimize();
            }
            this._unwatch(window);
        }
        this._dbus?.unexport();
        this._dbus = this._injections = this._capture = this._pending = null;
        this._shotId = this._createdId = this._monitorsId = 0;
        this._closedId = 0;
        this._hidden = [];
    }
}
