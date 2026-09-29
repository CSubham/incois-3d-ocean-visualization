import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// Observation dataset, time window and "Show floats" (IMAP s7-selection-controls,
// observation half). Markers are searched inside the model field's region.
import { Button, Select, Stack, Text, TextInput, Title } from "@mantine/core";
import { formatUtc } from "./format";
export function ObservationPanel({ observations, canSearch, onSelectVersion, onEditWindow, onShow }) {
    const { versions } = observations;
    return (_jsxs(Stack, { gap: "sm", component: "section", "aria-label": "Observations", children: [_jsx(Title, { order: 2, size: "h6", tt: "uppercase", c: "dimmed", children: "Observations" }), versions === null ? (_jsx(Text, { size: "sm", c: "red", children: "The observation catalogue could not be read." })) : versions.length === 0 ? (_jsx(Text, { size: "sm", c: "dimmed", children: "No observation datasets are stored yet." })) : (_jsxs(_Fragment, { children: [_jsx(Select, { label: "Instrument dataset", value: observations.versionId, allowDeselect: false, data: versions.map((v) => ({
                            value: v.dataset_version_id,
                            label: `${v.dataset_id} · ${v.vertical_kind} (${v.vertical_units})`,
                        })), onChange: (v) => v && onSelectVersion(v) }), _jsx(TextInput, { label: "From (UTC, ISO 8601)", value: observations.timeStart, onChange: (e) => onEditWindow({ timeStart: e.currentTarget.value }) }), _jsx(TextInput, { label: "To (UTC, ISO 8601)", value: observations.timeEnd, onChange: (e) => onEditWindow({ timeEnd: e.currentTarget.value }) }), _jsx(Button, { variant: "light", onClick: onShow, disabled: !canSearch, loading: observations.phase === "loading", children: "Show floats in this region" }), _jsxs(Text, { size: "xs", c: observations.phase === "failed" ? "red" : "dimmed", role: "status", children: [observations.phase === "shown" && (observations.count === 0
                                ? `No profiles between ${formatUtc(observations.timeStart)} and ${formatUtc(observations.timeEnd)} in this region.`
                                : `${observations.count} profiles shown. Select one on the globe for its profile.`), observations.phase === "failed" && observations.failure?.message] })] }))] }));
}
