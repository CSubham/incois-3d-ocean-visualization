import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// Loading, failure and unsupported states (IMAP s7-visible-failures):
// never a blank or silently stale view.
import { Alert, Group, Loader, Paper, Text } from "@mantine/core";
export function StatusBanner({ catalogue, request, renderer, displayProblem, hasProduct }) {
    if (renderer.phase === "unsupported")
        return _jsx(Alert, { color: "red", title: "3D view unavailable", role: "alert", children: renderer.reason });
    if (renderer.phase === "lost")
        return _jsx(Alert, { color: "red", title: "3D view stopped", role: "alert", children: renderer.reason });
    if (renderer.phase === "failed")
        return _jsx(Alert, { color: "red", title: "Display problem", role: "alert", children: renderer.reason });
    if (displayProblem)
        return _jsx(Alert, { color: "yellow", title: "Display setting not applied", role: "alert", children: displayProblem });
    if (request.phase === "loading") {
        return (_jsx(Paper, { px: "md", py: 8, withBorder: true, shadow: "md", role: "status", children: _jsxs(Group, { gap: "sm", children: [_jsx(Loader, { size: "xs" }), _jsx(Text, { size: "sm", children: request.retryFrom ? "Preparing a lower-density field…" : "Preparing the field…" })] }) }));
    }
    if (request.phase === "failed") {
        return (_jsxs(Alert, { color: "red", title: "The field could not be shown", role: "alert", children: [request.failure.message, hasProduct ? " The previous field is still shown." : ""] }));
    }
    if (catalogue.phase === "failed")
        return _jsx(Alert, { color: "red", title: "Catalogue unavailable", role: "alert", children: catalogue.message });
    if (!hasProduct && catalogue.phase === "ready") {
        return _jsx(Paper, { px: "md", py: 8, withBorder: true, shadow: "md", role: "status", children: _jsx(Text, { size: "sm", children: "Choose a selection and press Show field." }) });
    }
    return null;
}
