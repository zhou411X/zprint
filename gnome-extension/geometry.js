// Coordinates are Mutter stage units, never screenshot pixel coordinates.
export function toolbarRect(image, monitor, width, height) {
    const [x, y, w, h] = image;
    const [mx, my, mw, mh] = monitor;
    width = Math.min(width, mw);
    height = Math.min(height, mh);
    let top = y + h + 8;
    if (top + height > my + mh)
        top = y - height - 8;
    // Full-screen captures have no external space: keep controls on screen.
    if (top < my)
        top = Math.max(my, my + mh - height - 8);
    return [Math.max(mx, Math.min(x + w - width, mx + mw - width)),
        top, width, height].map(Math.round);
}
