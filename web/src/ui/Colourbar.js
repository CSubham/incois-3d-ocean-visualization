import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// The colourbar: palette, range, scale and units of what is on screen.
import { Group, Paper, Text } from "@mantine/core";
import { cssGradient } from "../renderer/colour";
export function Colourbar({ display, units, variable }) {
    const { minimum, maximum } = display.range;
    const middle = display.scale === "log" ? Math.sqrt(minimum * maximum) : (minimum + maximum) / 2;
    const fmt = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toPrecision(3));
    return (_jsxs(Paper, { p: "sm", w: 320, withBorder: true, shadow: "md", "aria-label": `Colour scale for ${variable}`, children: [_jsxs(Text, { size: "xs", c: "dimmed", mb: 6, children: [variable, " (", units, ") \u00B7 ", display.scale] }), _jsx("div", { className: "colour-bar", style: { background: cssGradient(display.palette) } }), _jsxs(Group, { justify: "space-between", mt: 4, className: "mono", children: [_jsx(Text, { size: "xs", children: fmt(minimum) }), _jsx(Text, { size: "xs", children: fmt(middle) }), _jsx(Text, { size: "xs", children: fmt(maximum) })] })] }));
}
