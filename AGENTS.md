# Agent instructions

INCOIS 3D Ocean Data Visualization System — Smart India Hackathon PS 26067.

A web-based platform that renders numerical ocean model fields in 3D alongside
in-situ instrument observations, so forecasters can compare model predictions
against observational evidence in one interactive view.

## Authority chain

Work downward. A document may never contradict the one above it.

1. `docs/project/SRS_Technical_Requirements_Mapping.txt` — **locked.** Sole
   requirements authority, 39 requirement IDs.
2. `docs/architecture/HLSA_...md` — **locked.** Seven-stage responsibility
   pipeline and requirement ownership. Defines responsibilities, selects no
   technology.
3. `docs/architecture/LLD_...md` — **incomplete, under active revision.**
   Solution modules, selected technology, decision record. Do not treat it as
   an approved basis for implementation until its status line says otherwise.

## Do not touch

- The two locked documents above. No edits, no new requirement IDs, no
  reinterpretation of wording.
- `data/raw/` sample files and their `.json` provenance sidecars. The sidecar
  records how a file was obtained; it must stay with its data file.
- `data/raw/model/incois_valueadded_currents/` — retained deliberately as a
  CF-validation reject fixture. It is **not** usable current data. Its sidecar
  explains why.

## The pipeline

`S1 Data Sources → S2 Ingestion → S3 Storage → S4 Processing → S5 Backend →
S6 3D Rendering → S7 UI`

Stage order is fixed by the HLSA. S2 is the only surface currently scaffolded,
at `ingestion/`.

## Rules

- Never invent a requirement ID. The 39 in the SRS are the complete set.
- Never claim a requirement is met without evidence — name the file, module or
  test that satisfies it.
- Source-mentioned technologies in the SRS (Cesium.js, PyNIO, OPeNDAP) remain
  unselected. The LLD records what was chosen and why.
- Sample data spans two NetCDF generations, four QC vocabularies and two
  vertical coordinate conventions on purpose. Parsers must handle the variety.

## Validation

No build or test commands exist yet. Add them here as each surface gains them.
