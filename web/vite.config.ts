import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// In development the API runs separately (uvicorn); proxying keeps the app
// same-origin exactly as it is when S5 serves the built files.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000" } },
  build: { outDir: "dist", sourcemap: true },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
