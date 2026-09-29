import { jsx as _jsx } from "react/jsx-runtime";
// Browser composition point: the one place implementations are chosen.
// Feature modules receive a DataClient and a RendererFactory, never a
// transport or an engine.
import "@mantine/core/styles.css";
import { createTheme, MantineProvider } from "@mantine/core";
import { createRoot } from "react-dom/client";
import { HttpDataClient } from "./api/client";
import { CesiumRenderer } from "./renderer/cesium/CesiumRenderer";
import { App } from "./ui/App";
import "./ui/styles.css";
// Points one layer accepts. A configured ceiling until a tested browser
// budget replaces it (IMAP s6-point-field-budget).
const RENDERER_MAXIMUM_POINTS = 500_000;
const theme = createTheme({ primaryColor: "cyan", defaultRadius: "sm" });
createRoot(document.getElementById("root")).render(_jsx(MantineProvider, { theme: theme, defaultColorScheme: "dark", children: _jsx(App, { client: new HttpDataClient(), createRenderer: () => new CesiumRenderer(RENDERER_MAXIMUM_POINTS) }) }));
