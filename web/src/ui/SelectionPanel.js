import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// Dataset, variable, time, region, depth and density selection
// (IMAP s7-selection-controls). A request is made only on "Show field".
import { Button, NumberInput, Select, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { formatUtc as utc } from "./format";
function versionLabel(version) {
    const time = version.time_values?.[0] ?? version.extent.time_start;
    return `${version.dataset} · ${time ? utc(time) : "time unknown"}`;
}
const num = (value) => (typeof value === "number" && Number.isFinite(value) ? value : null);
export function SelectionPanel({ catalogue, selection, loading, maximumPoints, onSelectVersion, onEdit, onShow }) {
    if (catalogue.phase !== "ready" || !selection) {
        return (_jsxs(Stack, { gap: "xs", children: [_jsx(Title, { order: 2, size: "h6", tt: "uppercase", c: "dimmed", children: "Data" }), _jsx(Text, { size: "sm", c: "dimmed", children: catalogue.phase === "loading" ? "Loading the catalogue…"
                        : catalogue.phase === "failed" ? catalogue.message
                            : "No model fields are stored yet." })] }));
    }
    const version = catalogue.versions.find((v) => v.id === selection.versionId);
    const times = version.time_values ?? (version.extent.time_start ? [version.extent.time_start] : []);
    const field = (key) => (value) => { const n = num(value); if (n !== null)
        onEdit({ [key]: n }); };
    return (_jsxs(Stack, { gap: "sm", component: "section", "aria-label": "Data selection", children: [_jsx(Title, { order: 2, size: "h6", tt: "uppercase", c: "dimmed", children: "Data" }), _jsx(Select, { label: "Dataset version", value: selection.versionId, allowDeselect: false, data: catalogue.versions.map((v) => ({ value: v.id, label: versionLabel(v) })), onChange: (v) => v && onSelectVersion(v) }), _jsx(Select, { label: "Variable", value: selection.variable, allowDeselect: false, data: version.variables.map((v) => ({ value: v.name, label: v.units ? `${v.name} (${v.units})` : v.name })), onChange: (v) => v && onEdit({ variable: v }) }), _jsx(Select, { label: "Time", value: selection.time, allowDeselect: false, searchable: times.length > 10, data: times.map((t) => ({ value: t, label: utc(t) })), onChange: (v) => v && onEdit({ time: v }) }), _jsxs(SimpleGrid, { cols: 2, spacing: "xs", children: [_jsx(NumberInput, { label: "West (\u00B0E)", value: selection.west, onChange: field("west"), decimalScale: 3 }), _jsx(NumberInput, { label: "East (\u00B0E)", value: selection.east, onChange: field("east"), decimalScale: 3 }), _jsx(NumberInput, { label: "South (\u00B0N)", value: selection.south, onChange: field("south"), decimalScale: 3 }), _jsx(NumberInput, { label: "North (\u00B0N)", value: selection.north, onChange: field("north"), decimalScale: 3 }), _jsx(NumberInput, { label: "Depth from (m)", value: selection.depthMinimum, onChange: field("depthMinimum"), min: 0 }), _jsx(NumberInput, { label: "Depth to (m)", value: selection.depthMaximum, onChange: field("depthMaximum"), min: 0 })] }), _jsx(NumberInput, { label: "Points to show", description: `Up to ${maximumPoints.toLocaleString()} for this view`, value: selection.maximumPoints, min: 1, max: maximumPoints, step: 10_000, thousandSeparator: ",", onChange: field("maximumPoints") }), _jsx(Button, { onClick: onShow, loading: loading, fullWidth: true, children: "Show field" })] }));
}
