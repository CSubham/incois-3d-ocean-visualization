import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// What is shown versus what exists (IMAP s7-point-field-sampling-state).
// The view is sampled source cells, never a complete-resolution volume.
import { Alert, Paper, Stack, Table, Text, Title } from "@mantine/core";
import { formatUtc } from "./format";
const n = (value) => value.toLocaleString();
export function SamplingDisclosure({ product, budget, shown, retry, verticalExaggeration }) {
    const p = product.product;
    const s = p.sampling;
    const share = s.original_point_count ? (100 * s.delivered_point_count) / s.original_point_count : 100;
    const rows = [
        ["Time", formatUtc(p.identity.time_value)],
        ["Dataset", `${p.identity.dataset_id} · ${p.identity.dataset_version_id}`],
        ["Depth", `positive ${p.spatial_reference.vertical_positive} (${p.coordinates.units.depth}), drawn ×${verticalExaggeration}`],
        ["Reference", `${p.spatial_reference.crs}, not reprojected`],
    ];
    return (_jsx(Paper, { p: "sm", withBorder: true, shadow: "md", "aria-label": "Sampling disclosure", children: _jsxs(Stack, { gap: 6, children: [_jsx(Title, { order: 2, size: "h6", children: s.is_lossy ? "Sampled view" : "Every selected cell" }), _jsxs(Text, { size: "xs", children: [n(s.delivered_point_count), " of ", n(s.original_point_count), " source cells delivered (", share < 1 ? share.toFixed(2) : share.toFixed(0), "%), chosen evenly by grid index with no interpolation.", shown && _jsxs(_Fragment, { children: [" ", n(shown.points), " have values and are drawn; ", n(shown.hiddenMissing), " are land or missing and are not drawn."] })] }), budget?.reduced_by_server && (_jsx(Alert, { color: "yellow", p: 6, children: _jsxs(Text, { size: "xs", children: ["The server lowered the point budget from ", n(budget.requested_points ?? 0), " to ", n(budget.effective_points), "."] }) })), retry && (_jsx(Alert, { color: "yellow", p: 6, children: _jsxs(Text, { size: "xs", children: ["Re-requested at ", n(retry.to), " points because ", n(retry.from), " exceeded this view's limit."] }) })), _jsx(Table, { withRowBorders: false, verticalSpacing: 1, children: _jsx(Table.Tbody, { children: rows.map(([k, v]) => (_jsxs(Table.Tr, { children: [_jsx(Table.Td, { w: 80, children: _jsx(Text, { size: "xs", c: "dimmed", children: k }) }), _jsx(Table.Td, { children: _jsx(Text, { size: "xs", children: v }) })] }, k))) }) })] }) }));
}
