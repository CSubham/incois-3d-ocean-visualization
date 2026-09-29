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

Read **`docs/STATUS.md`** first. It is the one page that says what is built,
what is not, and which document currently governs what.

## Rules

- Never invent a requirement ID. The 39 in the SRS are the complete set.
- Never claim a requirement is met without evidence — name the file, module or
  test that satisfies it.
- Source-mentioned technologies in the SRS (Cesium.js, PyNIO, OPeNDAP) remain
  unselected. The LLD records what was chosen and why.
- Sample data spans two NetCDF generations, four QC vocabularies and two
  vertical coordinate conventions on purpose. Parsers must handle the variety.
- S2 reaches every source through `SourcePort` and hands off through
  `StoragePort`. Adding a source means an adapter plus one entry in
  `ingestion/adapters/__init__.py`; the application service must stay free of
  provider conditionals and file-format branching.
- Local file sources are archived in `archive/local-sources/`, not deleted.
  Read its README before reinstating or duplicating them.
- Where this repository departs from a design document, record it in the
  Decision record, not by editing the document to match:
  <https://linear.app/rudrav1/document/decision-record-d65cd64aa414>
- Documents have one home each. Requirements, architecture and decisions live
  in Linear; `AGENTS.md`, `docs/STATUS.md`, `ingestion/README.md` and the code
  live here. See the Document map:
  <https://linear.app/rudrav1/document/document-map-97246882b585>

## Agent work packets

These rules apply to every coding or review assignment unless its prompt
explicitly narrows them. Prompts should state only the goal, IMAP refs, branch
and base, allowed area, task-specific constraints, checks and definition of
done; do not repeat this section in every prompt.

- Start with `docs/STATUS.md`, then use Graft for code context and inspect the
  assigned IMAP nodes. The authority chain above always wins over a prompt,
  Graft result or IMAP item.
- One work packet uses one feature or review branch from the stated base.
  Never develop on `main`, reuse a merged branch or mix unrelated work into the
  packet. Use an isolated worktree when agents run concurrently.
- Stay inside the prompt's allowed files. Do not add unrelated cleanup,
  dependency upgrades, schema changes or architecture changes to make the task
  convenient.
- Preserve the fixed S1 through S7 responsibilities. Core workflows depend on
  semantic contracts; provider, database, cloud, transport, framework and
  renderer details stay inside replaceable adapters selected at composition.
- Preserve source values, units, masks, coordinates, vertical and time context,
  identity and provenance. Any sampling, interpolation, aggregation,
  transformation or loss must be explicit, scientifically justified and
  represented in the resulting contract.
- The Azure CLI may be available, but never authenticate, inspect a
  subscription, provision resources or change cloud state unless the work
  packet explicitly assigns that operation. Keep credentials out of code and
  keep cloud implementations behind the relevant boundary.
- In a coordinated multi-agent run, the moderator owns shared `.imap/map.db`
  assignment and status changes unless a prompt explicitly delegates them.
  Workers inspect the assigned refs and report them, but do not commit competing
  SQLite changes from feature branches. Run `imap check` when practical.
- Keep validation proportional and staged. While coding, run only the smallest
  test file or test case that exercises the changed behavior. Do not rerun a
  broad suite after every edit. Prefer quiet pytest output (`-q --tb=short`);
  use verbose output only for a specific failure being diagnosed, and do not
  run coverage unless the packet requests it.
- Once the implementation has settled, run the packet's focused tests once.
  Run an affected stage suite once before commit only when shared behavior or a
  stage contract changed. Leaf modules and test-only work do not require the
  whole repository suite unless the prompt says so.
- Run live, network, database, browser or deployment checks only when the packet
  explicitly assigns them, and normally once after focused tests pass. Never
  repeat an unchanged expensive check merely to collect the same evidence.
- Do not reinstall dependencies when the existing environment can import and
  run the assigned code. Install only a missing dependency or a dependency
  intentionally changed by the packet.
- Run compile/type/build checks, `git diff --check`, `imap check`, and
  `graft build` at most once at the final verification point when applicable.
  `graft build` is for substantive code changes, not documentation-only or
  test-only packets. In coordinated runs, the moderator runs the final combined
  cross-branch suite and merge-gate checks.
- If a broad or unrelated test fails, reproduce the specific failure once in
  isolation. Fix it only when it is in scope; otherwise report the command,
  failure and isolation result instead of repeatedly rerunning the broad suite.
  Tests are network-free unless the packet explicitly defines an integration
  environment.
- Treat requirement coverage honestly. Partial or prototype evidence remains
  partial; never mark a requirement or IMAP responsibility implemented without
  observable evidence and moderator review.
- Stop and report instead of guessing when source documents conflict, required
  design is unapproved, the branch/base is unclear, ownership would cross a
  stage boundary, forbidden files are required, or unrelated tests fail for an
  unknown reason.
- Return: branch and commit; summary; files inspected and changed; tests and
  results; IMAP refs; blockers; risks; deviations or limitations; and the next
  suggested step. Reviewers lead with severity-ordered findings and file/line
  references.

## Validation

S2 ingestion validation:

```bash
.venv/bin/pip install -r ingestion/requirements.txt
.venv/bin/python -m pytest ingestion/tests -q
.venv/bin/python -m compileall -q ingestion
.venv/bin/python -m uvicorn ingestion.web:app --port 8000
```

The tests need no network: the workflow is exercised through a stand-in
source in `ingestion/tests/fakes.py`. Running the application does reach
INCOIS.

## Context graph (Graft)

[Graft](https://github.com/trailhq/Graft) indexes this repo into a queryable
context graph. Wired for both Claude Code (`.claude/`, `.mcp.json`) and Codex
(`AGENTS.md`, `~/.codex/`). Install with `npm install -g @nanonets/graft`, then
`graft build`. The generated `graft/` directory is git-ignored — each person
builds their own.

**The graph is derived, never authoritative.** The authority chain above still
governs; nothing in `graft/` may be cited as a requirement or design decision.
The block below is generated by `graft init` — edit around it, not inside it.

Actively use Graft and IMAP whenever working in this repository. Use Graft for
source orientation before grepping or opening code, and use IMAP for
responsibility, assignment and progress state. After substantive code changes,
refresh Graft with `graft build`. For standalone work, update the relevant IMAP
nodes when taking on, progressing or completing work. In coordinated runs,
follow the moderator-owned IMAP rule above. Run `imap check` when practical.

<!-- graft:start -->
## Graft — repo context graph

This repo is indexed in `graft/`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run `graft map` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run `graft ask "<your question>" --source` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; `--full` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  `covers:` file:line spans and edit straight from `--source`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run `graft grep "<literal>"` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw `grep -rn` only for unindexed files.
- `graft skeleton <file>` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- `graft callers <symbol>` gives precomputed, exact edges — who calls this.
  Add `--direction out` for what it calls, or `--depth N` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: `graft/INDEX.md` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry `[scope/]` labels naming which one they're from. Narrow with
  `graft ask "<task>" --in <scope>/` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with `graft build` (deterministic,
no API key, $0).
<!-- graft:end -->
