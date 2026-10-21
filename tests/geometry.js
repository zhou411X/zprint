import {toolbarRect} from '../gnome-extension/geometry.js';

const cases = [
    [[300, 200, 400, 200], [0, 0, 1920, 1080], 600, 52, [100, 408, 600, 52]],
    [[100, 950, 400, 120], [0, 0, 1920, 1080], 600, 52, [0, 890, 600, 52]],
    [[0, 0, 1920, 1080], [0, 0, 1920, 1080], 600, 52, [1320, 1020, 600, 52]],
    [[-1800, 150, 200, 80], [-1920, 0, 1920, 1080], 600, 52, [-1920, 238, 600, 52]],
    [[20, 20, 10, 10], [0, 0, 480, 800], 600, 52, [0, 38, 480, 52]],
];
for (const [image, monitor, w, h, expected] of cases) {
    const actual = toolbarRect(image, monitor, w, h);
    if (JSON.stringify(actual) !== JSON.stringify(expected))
        throw new Error(`Expected ${expected}; got ${actual}`);
}
print(`Geometry: ${cases.length} passed`);
