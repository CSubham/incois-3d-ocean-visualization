// Browser composition point: the one place implementations are chosen.
// Feature modules receive a DataClient and a RendererFactory, never a
// transport or an engine.

import { createRoot } from "react-dom/client";

import { HttpDataClient } from "./api/client";
import { ThreeRenderer } from "./renderer/three/ThreeRenderer";
import { App } from "./ui/App";
import "./ui/styles.css";

// Points one layer accepts. A configured ceiling until a tested browser
// budget replaces it (IMAP s6-point-field-budget).
const RENDERER_MAXIMUM_POINTS = 500_000;

createRoot(document.getElementById("root")!).render(
  <App
    client={new HttpDataClient()}
    createRenderer={() => new ThreeRenderer(RENDERER_MAXIMUM_POINTS)}
  />,
);
