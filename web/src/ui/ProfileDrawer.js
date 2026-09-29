import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// The selected float's profile beside the globe (IMAP s7-profile-chart):
// exact identity, time and position, and a Plotly depth- or pressure-versus-
// value chart. Plotly is loaded only when the first profile opens.
import { Alert, Drawer, Group, Loader, Stack, Text } from "@mantine/core";
import { useEffect, useMemo, useRef } from "react";
import { formatUtc } from "./format";
import { profileFigure } from "./profileFigure";
function ProfileChart({ figure }) {
    const element = useRef(null);
    useEffect(() => {
        let cancelled = false;
        const target = element.current;
        void import("plotly.js-basic-dist-min").then((Plotly) => {
            if (cancelled || !target)
                return;
            void Plotly.react(target, figure.data, figure.layout, { displaylogo: false, responsive: true });
        });
        return () => {
            cancelled = true;
            if (target)
                void import("plotly.js-basic-dist-min").then((Plotly) => Plotly.purge(target));
        };
    }, [figure]);
    return _jsx("div", { ref: element, style: { width: "100%", height: 460 }, "aria-label": "Profile chart" });
}
export function ProfileDrawer({ profile, onClose }) {
    const pick = profile.pick;
    // One figure per profile, so Plotly redraws only when the profile changes.
    const figure = useMemo(() => (profile.profile ? profileFigure(profile.profile) : null), [profile.profile]);
    return (_jsxs(Drawer, { opened: profile.phase !== "closed", onClose: onClose, position: "right", size: 480, title: pick ? `Float ${pick.platformId} · cycle ${pick.cycle}` : "Profile", withOverlay: false, lockScroll: false, trapFocus: false, children: [pick && (_jsxs(Text, { size: "xs", c: "dimmed", mb: "sm", className: "mono", children: [formatUtc(pick.observedAt), " \u00B7 ", pick.latitude.toFixed(3), "\u00B0N ", pick.longitude.toFixed(3), "\u00B0E"] })), profile.phase === "loading" && _jsxs(Group, { gap: "sm", children: [_jsx(Loader, { size: "xs" }), _jsx(Text, { size: "sm", children: "Loading the profile\u2026" })] }), profile.phase === "failed" && (_jsx(Alert, { color: "red", title: "The profile could not be shown", role: "alert", children: profile.failure?.message })), profile.phase === "shown" && profile.profile && figure && (_jsxs(Stack, { gap: "xs", children: [_jsx(ProfileChart, { figure: figure }), profile.profile.variables.map((variable) => (_jsxs(Text, { size: "xs", c: "dimmed", children: [variable.name, " QC:", " ", variable.qcMeanings
                                ? [...variable.qcMeanings].map(([flag, meaning]) => `${flag} = ${meaning}`).join(", ")
                                : variable.qcFlags ? "flags shown as recorded; the source does not declare their meanings" : "no QC variable"] }, variable.name)))] }))] }));
}
