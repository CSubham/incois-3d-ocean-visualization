import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// The source cell under the pointer, in physical units.
import { Paper, Table, Text } from "@mantine/core";
export function HoverReadout({ sample, units, variable }) {
    const rows = [
        [variable, `${sample.value.toFixed(3)} ${units}`],
        ["Latitude", `${sample.latitude.toFixed(3)}°`],
        ["Longitude", `${sample.longitude.toFixed(3)}°`],
        ["Depth", `${sample.depth.toFixed(1)} m`],
    ];
    return (_jsx(Paper, { p: "xs", withBorder: true, shadow: "md", "aria-live": "polite", "aria-label": "Value under pointer", children: _jsx(Table, { withRowBorders: false, verticalSpacing: 2, className: "mono", children: _jsx(Table.Tbody, { children: rows.map(([k, v]) => (_jsxs(Table.Tr, { children: [_jsx(Table.Td, { children: _jsx(Text, { size: "xs", c: "dimmed", children: k }) }), _jsx(Table.Td, { children: _jsx(Text, { size: "xs", fw: 500, children: v }) })] }, k))) }) }) }));
}
