// Colour mapping for scalar values. Pure: no rendering engine involved.
//
// Palettes are perceptually uniform (viridis, cividis) or designed for
// temperature (cmocean thermal), given as evenly spaced anchor colours and
// interpolated linearly in sRGB.
const ANCHORS = {
    viridis: ["#440154", "#482777", "#3f4a8a", "#31678e", "#26838f",
        "#1f9d8a", "#6cce5a", "#b6de2b", "#fee825"],
    cividis: ["#00204c", "#213d6b", "#555b6c", "#7b7a77", "#a59c74",
        "#d3c064", "#ffe945"],
    thermal: ["#042333", "#2c3395", "#744992", "#b15f82", "#eb7655",
        "#fbb43d", "#e8fa5b"],
};
export const PALETTES = Object.keys(ANCHORS);
function rgb(hex) {
    const n = parseInt(hex.slice(1), 16);
    return [(n >> 16) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}
const RGB = Object.fromEntries(PALETTES.map((name) => [name, ANCHORS[name].map(rgb)]));
/** Colour at position t in [0, 1]; values outside are clamped. */
export function paletteColour(palette, t) {
    const anchors = RGB[palette];
    const clamped = Math.min(1, Math.max(0, t));
    const scaled = clamped * (anchors.length - 1);
    const i = Math.min(anchors.length - 2, Math.floor(scaled));
    const f = scaled - i;
    const [a, b] = [anchors[i], anchors[i + 1]];
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}
export class ScaleError extends Error {
}
/** Why a logarithmic scale cannot be used for this range, or null if it can. */
export function logScaleProblem(minimum, maximum) {
    if (!(minimum > 0))
        return "a logarithmic scale needs a range minimum above zero";
    if (!(maximum > minimum))
        return "the range maximum must exceed the minimum";
    return null;
}
/** Position of a value within the range, before clamping. */
export function normalise(value, minimum, maximum, scale) {
    if (scale === "log") {
        const problem = logScaleProblem(minimum, maximum);
        if (problem)
            throw new ScaleError(problem);
        if (!(value > 0))
            return 0;
        return (Math.log(value) - Math.log(minimum)) / (Math.log(maximum) - Math.log(minimum));
    }
    if (maximum === minimum)
        return 0.5;
    return (value - minimum) / (maximum - minimum);
}
/** CSS gradient of a palette, for the colourbar. */
export function cssGradient(palette) {
    return `linear-gradient(to right, ${ANCHORS[palette].join(", ")})`;
}
