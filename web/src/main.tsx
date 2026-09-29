// Browser composition point: the one place implementations are chosen.
// Feature modules receive a DataClient and a RendererFactory, never a
// transport or an engine.

import "@mantine/core/styles.css";
import { createTheme, MantineProvider } from "@mantine/core";
import { createRoot } from "react-dom/client";

import { HttpDataClient } from "./api/client";
import { CesiumRenderer } from "./renderer/cesium/CesiumRenderer";
import { Viewer } from "./ui/Viewer";
import "./ui/styles.css";

// Points one layer accepts. A configured ceiling until a tested browser
// budget replaces it (IMAP s6-point-field-budget).
const RENDERER_MAXIMUM_POINTS = 500_000;
// Cells one surface layer carries: about a full-HD screen. Configured, not
// yet a tested browser budget; S7 sends it to S5 as the view budget.
const RENDERER_MAXIMUM_SURFACE_CELLS = 2_000_000;

const theme = createTheme({ primaryColor: "cyan", defaultRadius: "sm" });

createRoot(document.getElementById("root")!).render(
  <MantineProvider theme={theme} defaultColorScheme="dark">
    <Viewer
      client={new HttpDataClient()}
      createRenderer={() => new CesiumRenderer(RENDERER_MAXIMUM_POINTS, RENDERER_MAXIMUM_SURFACE_CELLS)}
    />
  </MantineProvider>,
);
