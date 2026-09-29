import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { viteStaticCopy } from "vite-plugin-static-copy";
// CesiumJS loads workers, widgets and its bundled Natural Earth II imagery at
// runtime from CESIUM_BASE_URL (set in index.html). They are copied into the
// build so the app needs no CDN, token or network beyond its own origin.
const cesium = "node_modules/cesium/Build/Cesium";
export default defineConfig({
    plugins: [
        react(),
        viteStaticCopy({
            targets: ["Workers", "ThirdParty", "Assets", "Widgets"].map((dir) => ({
                src: `${cesium}/${dir}`, dest: "cesium",
                // keep Workers/, Assets/… but drop node_modules/cesium/Build/Cesium/
                rename: { stripBase: 4 },
            })),
        }),
    ],
    // In development the API runs separately; proxying keeps the app
    // same-origin exactly as it is when S5 serves the built files.
    server: { proxy: { "/api": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000" } },
    build: { outDir: "dist", sourcemap: true, chunkSizeWarningLimit: 6000 },
    test: { environment: "node", include: ["src/**/*.test.ts"] },
});
