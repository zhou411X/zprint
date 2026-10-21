import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import {SelectArea} from 'resource:///org/gnome/shell/ui/screenshot.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

// Reuse GNOME's modal grab, stage coordinates and reverse-drag geometry, but
// present only a frozen desktop and a selection. No system screenshot dialog.
export const CaptureSelection = GObject.registerClass(
class CaptureSelection extends SelectArea {
    _init(content) {
        super._init();
        const backdrop = new Clutter.Actor({content, width: global.stage.width,
            height: global.stage.height, content_gravity: Clutter.ContentGravity.RESIZE_FILL});
        this.insert_child_at_index(backdrop, 0);
        this._shades = Array.from({length: 4}, () => {
            const shade = new St.Widget({style: 'background-color: rgba(0,0,0,0.48);'});
            this.insert_child_below(shade, this._rubberband);
            return shade;
        });
        this._rubberband.set_style('border: 2px solid #68a7ff; background-color: transparent;');
        const monitor = Main.layoutManager.primaryMonitor;
        this._hint = new St.Label({text: '拖选截图区域 · 松开开始标记 · Esc / 右键取消',
            style: 'background-color: rgba(20,24,32,0.9); color: white; padding: 10px 16px; border-radius: 8px;'});
        this.add_child(this._hint);
        this._hint.set_position(monitor.x + 24, monitor.y + 48);
        this._shade(0, 0, 0, 0);
    }

    _shade(x, y, width, height) {
        const w = global.stage.width, h = global.stage.height;
        const boxes = [[0, 0, w, y], [0, y, x, height],
            [x + width, y, w - x - width, height], [0, y + height, w, h - y - height]];
        boxes.forEach(([left, top, bw, bh], i) => {
            this._shades[i].set_position(left, top);
            this._shades[i].set_size(bw, bh);
        });
    }

    vfunc_motion_event(event) {
        super.vfunc_motion_event(event);
        if (this._startX !== -1) {
            const r = this._getGeometry();
            this._shade(r.x, r.y, r.width, r.height);
            this._hint.text = `${r.width} × ${r.height} · 松开开始标记 · Esc / 右键取消`;
        }
        return Clutter.EVENT_STOP;
    }

    vfunc_button_press_event(event) {
        if (event.get_button() === Clutter.BUTTON_SECONDARY)
            this.cancel();
        else if (event.get_button() === Clutter.BUTTON_PRIMARY)
            super.vfunc_button_press_event(event);
        return Clutter.EVENT_STOP;
    }

    vfunc_button_release_event(event) {
        if (event.get_button() !== Clutter.BUTTON_PRIMARY || this._startX === -1)
            return Clutter.EVENT_STOP;
        super.vfunc_motion_event(event);
        const r = this._getGeometry();
        if (r.width < 2 || r.height < 2) {
            this._startX = this._startY = -1;
            this._rubberband.hide();
            this._shade(0, 0, 0, 0);
            return Clutter.EVENT_STOP;
        }
        this._result = r;
        this.hide();
        this._grabHelper.ungrab();
        return Clutter.EVENT_STOP;
    }

    vfunc_key_press_event(event) {
        if (event.get_key_symbol() === Clutter.KEY_Escape) {
            this.cancel();
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    }

    cancel() {
        this._result = null;
        this.hide();
        this._grabHelper.ungrab();
    }
});
