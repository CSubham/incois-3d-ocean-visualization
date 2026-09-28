# Web app (S6 rendering, S7 interface)

Static browser app: React + TypeScript shell, Three.js on WebGL2 behind the
renderer facade in `src/renderer/contract.ts`. Implementations are chosen only
in `src/main.tsx`.

```bash
npm ci
npm test            # unit tests, including the Python-written wire fixture
npm run build       # typecheck + dist/
```

S5 serves `dist/` from the same origin when it exists
(`uvicorn serving.compose:create_default_app --factory`). For development run
`npm run dev`; it proxies `/api` to the API on port 8000.

`test-fixtures/` is written by `serving/tests/test_wire.py`; regenerate with
`WIRE_GOLDEN_UPDATE=1` only when the wire format changes on purpose.
