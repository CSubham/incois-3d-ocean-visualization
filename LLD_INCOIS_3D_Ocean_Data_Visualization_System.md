## Low-Level Design and Solution Document

INCOIS 3D Ocean Data Visualization System
Problem Statement ID: 26067
Requirements authority: SRS_Technical_Requirements_Mapping.txt
Architecture authority: HLSA_INCOIS_3D_Ocean_Data_Visualization_System.md
Purpose: define the actual solution modules inside each pipeline stage, how each module works, which technology implements it, and what it hands to the next stage.
Audience: student development team building the system end to end.

The seven-stage pipeline is fixed by the HLSA and is preserved here. This document adds module-level solution detail and selected technology. It does not change any requirement or stage boundary.

### 1. Overall selected solution

Ingestion and processing are written in Python because xarray decodes CF-compliant NetCDF directly and pandas reads the delimited observation formats. Curated grids live as files on one Azure Files share, mounted into both the API and GeoServer containers, because GeoServer reads NetCDF from a filesystem path and Container Apps can mount only Azure Files. Searchable metadata and observations live in PostgreSQL with PostGIS. FastAPI serves the browser, GeoServer serves OGC clients, and the browser renders with Three.js on WebGL2. Everything runs as containers, so the same images redeploy on INCOIS infrastructure.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 380, "rankSpacing": 40, "nodeSpacing": 30}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    S1["S1 DATA SOURCES<br/>INCOIS model NetCDF<br/>Argo, Glider, CTD, BGC<br/>Azure: Files share, raw/ folder"]:::ext
    S2["S2 DATA INGESTION<br/>Python, xarray, pandas<br/>Azure: Container Apps Job"]:::proc
    S3["S3 DATA STORAGE<br/>Azure Files + PostgreSQL/PostGIS<br/>Azure: Storage + Flexible Server"]:::store
    S4["S4 DATA PROCESSING<br/>xarray, numpy, scikit-image<br/>Azure: in the S5 API container"]:::proc
    S5["S5 BACKEND / SERVING<br/>FastAPI + GeoServer<br/>Azure: Container Apps"]:::serve
    S6["S6 3D RENDERING<br/>Three.js on WebGL2<br/>Runs in the user browser"]:::client
    S7["S7 USER INTERFACE<br/>React, TypeScript, Plotly<br/>Azure: Static Web Apps"]:::client
    PORT["EXTERNAL OCEAN PORTALS<br/>OGC WMS/WCS clients"]:::ext

    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7
    S7 -.->|"selections and data needs"| S5
    S5 -.->|"WMS/WCS"| PORT

    classDef ext fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef proc fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef store fill:#EDE9FE,stroke:#6D28D9,color:#1F2937;
    classDef serve fill:#FFEDD5,stroke:#C2410C,color:#1F2937;
    classDef client fill:#ECFDF5,stroke:#059669,color:#0F172A;
```

### 2. S1 Data Sources

Stage purpose: define exactly which files enter the system and where they land.

Selected stage solution: INCOIS model runs and instrument feeds write files into one Azure Files share under a fixed path convention, so every later stage sees the same ordinary filesystem. Nothing is transformed here. A Source Registry file, held in the code repository, is the one place that declares every known feed, so adding a source later is a configuration change rather than a code change.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 380, "rankSpacing": 40, "nodeSpacing": 30}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    IN["INPUT GATE<br/>Files produced outside the system"]:::gate
    P["STAGE PLATFORM<br/>Azure Files share, raw/ folder<br/>mounted by the S2 job"]:::plat
    M1["MODEL OUTPUT FEED<br/>In: model run NetCDF<br/>Does: land 3D fields per run<br/>Out: raw/model/run-id/*.nc"]:::mod
    M2["OBSERVATION FEED<br/>In: Argo, Glider NetCDF;<br/>CTD, BGC delimited text<br/>Does: land per instrument batch<br/>Out: raw/obs/source/*"]:::mod
    M3["SOURCE REGISTRY<br/>In: one YAML entry per feed<br/>Does: declare format, path glob,<br/>variable and column names<br/>Out: feed definition for S2"]:::mod
    OUT["OUTPUT GATE<br/>Raw files plus source id<br/>and registry entry"]:::out

    IN --> P --> M1
    IN --> M2
    M1 --> M3
    M2 --> M3
    M3 --> OUT

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef plat fill:#F1F5F9,stroke:#64748B,color:#1F2937;
```

### 3. S2 Data Ingestion

Stage purpose: turn raw source files into validated, canonically named datasets and catalogue rows.

Selected stage solution: one Python container runs on a schedule as an Azure Container Apps Job. The Source Adapter reads the registry entry and dispatches to the NetCDF parser or the text parser. xarray opens NetCDF with CF decoding enabled, which resolves time units and packed values automatically. The Field Mapper renames source variables to the canonical set the rest of the system uses. Anything failing the CF and dimension check is moved aside with a reason rather than entering the curated store.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 380, "rankSpacing": 40, "nodeSpacing": 30}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    IN["INPUT GATE<br/>Raw file, source id,<br/>registry entry"]:::gate
    P["STAGE PLATFORM<br/>Python 3.12 container<br/>Azure Container Apps Job, schedule"]:::plat
    M1["SOURCE ADAPTER<br/>In: registry entry<br/>Does: choose reader by format<br/>Out: reader plus field map"]:::mod
    M2["NETCDF PARSER<br/>In: .nc file<br/>Does: open with decode_cf,<br/>read dims, vars, attributes<br/>Using: xarray, netcdf4<br/>Out: dataset plus CF metadata"]:::mod
    M3["DELIMITED TEXT PARSER<br/>In: CSV or ASCII profile file<br/>Does: read table, type columns<br/>Using: pandas.read_csv<br/>Out: observation dataframe"]:::mod
    M4["CANONICAL FIELD MAPPER<br/>In: dataset or dataframe<br/>Does: rename to canonical names<br/>lat, lon, depth, time, temp,<br/>sal, chl; check CF and dims<br/>Out: canonical dataset"]:::mod
    M5["CATALOGUE WRITER<br/>In: canonical dataset<br/>Does: write curated file and<br/>insert catalogue rows; files<br/>already catalogued are skipped<br/>Out: curated path plus row ids"]:::mod
    F["REJECTED<br/>Missing CF attrs or dims<br/>Move to raw/rejected<br/>with reason, log, continue"]:::fail
    OUT["OUTPUT GATE<br/>Curated NetCDF on the share,<br/>observation rows, catalogue rows"]:::out

    IN --> P --> M1
    M1 --> M2
    M1 --> M3
    M2 --> M4
    M3 --> M4
    M4 -->|"valid"| M5
    M4 -->|"invalid"| F
    M5 --> OUT

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef plat fill:#F1F5F9,stroke:#64748B,color:#1F2937;
    classDef fail fill:#FFE4E6,stroke:#BE123C,color:#1F2937;
```

### 4. S3 Data Storage / Management

Stage purpose: keep curated data addressable by variable, depth, time and area.

Selected stage solution: gridded model data stays in its native CF NetCDF form as files on the Azure Files share, because xarray and GeoServer both read that format directly from a mounted path and no conversion or second copy is needed. Point observations go into PostgreSQL, where PostGIS gives a geometry column and a spatial index so marker queries by map extent are fast. The catalogue is the join between the two: it records which variable, depth range, time range and bounding box each curated file covers.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 380, "rankSpacing": 40, "nodeSpacing": 30}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    IN["INPUT GATE<br/>Canonical datasets and<br/>observation rows from S2"]:::gate
    P["STAGE PLATFORM<br/>Azure Files share, curated/ folder<br/>Azure PostgreSQL Flexible Server<br/>with PostGIS extension"]:::plat
    M1["CURATED GRID STORE<br/>In: canonical model dataset<br/>Does: store CF NetCDF at<br/>curated/model/run/var.nc<br/>Out: stable mounted file path"]:::mod
    M2["OBSERVATION STORE<br/>In: observation rows<br/>Does: hold profiles and levels<br/>with a PostGIS point geometry<br/>Out: queryable observations"]:::mod
    M3["DATASET CATALOGUE<br/>In: file path plus metadata<br/>Does: record variable, depth<br/>range, time range, bbox, path<br/>Out: one lookup for all datasets"]:::mod
    M4["SPATIAL AND TIME INDEX<br/>In: geometry and time columns<br/>Does: GiST index on geometry,<br/>B-tree index on time<br/>Out: fast extent and range query"]:::mod
    OUT["OUTPUT GATE<br/>Addressable grids plus<br/>queryable catalogue and points"]:::out

    IN --> P --> M1
    IN --> M2
    M1 --> M3
    M2 --> M3
    M3 --> M4 --> OUT

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef plat fill:#F1F5F9,stroke:#64748B,color:#1F2937;
```

### 5. S4 Data Processing

Stage purpose: produce exactly the array, mesh or series that one requested view needs.

Selected stage solution: processing runs on demand inside the API container rather than as a separate service, which removes a deployment and keeps the request path short. The Model Subsetter is the common front door: it opens the curated file lazily and selects by variable, time, depth and bounding box, so only the requested block is read. The Volume Builder serves the full water column, resampling onto a target grid whose size is a deployment setting rather than the model's native resolution: a native grid across every depth level is far larger than one browser request should carry, and time animation asks for one volume per step. The Level Extractor serves one depth level, returning a scalar field for slices and sampled u,v pairs for current vectors, since both describe the same chosen level. Profiles are point data, so they come from the observation store on their own path.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 380, "rankSpacing": 40, "nodeSpacing": 30}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    IN["INPUT GATE<br/>View request: variable, time,<br/>depth, extent, instrument id"]:::gate
    P["STAGE PLATFORM<br/>Python in the S5 API container<br/>xarray, numpy, scikit-image"]:::plat
    M1["MODEL SUBSETTER<br/>In: request plus catalogue row<br/>Does: open lazily, .sel by var,<br/>time, depth and bbox<br/>Out: subset array plus coords"]:::mod
    M2["VOLUME BUILDER<br/>In: subset array<br/>Does: resample to a regular<br/>lat-lon-depth grid of configured<br/>size, scale to 8-bit<br/>Out: volume bytes plus range"]:::mod
    M3["LEVEL EXTRACTOR<br/>In: volume grid, depth level<br/>Does: take one level as a 2D<br/>field; sample u,v on that level<br/>Out: slice array, vector samples"]:::mod
    M4["ISOSURFACE GENERATOR<br/>In: volume, threshold value<br/>Does: marching cubes<br/>Using: skimage.measure<br/>Out: vertices and triangles"]:::mod
    M5["PROFILE BUILDER<br/>In: instrument id<br/>Does: PostGIS lookup of levels,<br/>order by depth, add timestamps<br/>Out: depth, value, time series"]:::mod
    OUT2["OUTPUT GATE B<br/>Profile series for S5"]:::out
    OUT1["OUTPUT GATE A<br/>Volume, slice, vectors or mesh<br/>for S5"]:::out

    IN --> P
    P --> M1
    P --> M5
    M1 --> M2
    M2 --> M3
    M2 --> M4
    M5 --> OUT2
    M2 --> OUT1
    M3 --> OUT1
    M4 --> OUT1

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef plat fill:#F1F5F9,stroke:#64748B,color:#1F2937;
```

### 6. S5 Backend / Data Serving

Stage purpose: expose prepared data to the browser and publish standards-based services to external portals.

Selected stage solution: FastAPI gives typed request validation and generated OpenAPI documentation, which matters for a student team because the frontend contract is readable without extra work. Three API modules cover the three things the browser asks for: what exists, field data for a view, and observations. GeoServer runs as a second container with the same share mounted read-only and points its NetCDF data store at the same curated files, so WMS and WCS are served without duplicating data.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 380, "rankSpacing": 40, "nodeSpacing": 30}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    IN["INPUT GATE<br/>Browser requests and<br/>portal WMS/WCS requests"]:::gate
    P["STAGE PLATFORM<br/>Azure Container Apps<br/>FastAPI container + GeoServer<br/>container, HTTP scaling"]:::plat
    M1["CATALOGUE API<br/>In: browse request<br/>Does: list datasets, variables,<br/>depth levels, time steps<br/>Out: options for the controls"]:::mod
    M2["FIELD DATA API<br/>In: variable, time, depth, view<br/>Does: call S4, return volume,<br/>slice, isosurface or vectors<br/>Out: typed array plus range"]:::mod
    M3["OBSERVATION API<br/>In: map extent or instrument id<br/>Does: PostGIS extent query,<br/>or return built profile<br/>Out: markers or profile series"]:::mod
    M4["OGC SERVICE<br/>In: WMS/WCS request<br/>Does: publish curated NetCDF<br/>with time and elevation dims<br/>Using: GeoServer NetCDF plugin<br/>Out: map images and coverages"]:::mod
    OUT["OUTPUT GATE<br/>JSON and binary to browser;<br/>WMS/WCS to portals"]:::out

    IN --> P
    IN --> M4
    P --> M1
    P --> M2
    M1 --> M3
    M2 --> M3
    M3 --> OUT
    M4 --> OUT

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef plat fill:#F1F5F9,stroke:#64748B,color:#1F2937;
```

### 7. S6 3D Rendering / Visualization

Stage purpose: draw the model field and the instrument markers together in one interactive 3D scene.

Selected stage solution: Three.js on WebGL2 is selected because volumetric rendering needs a real 3D texture, which WebGL2 provides and WebGL1 does not. The volume arrives as a byte array, is uploaded once as a Data3DTexture, and a fragment shader ray-marches it, applying the colour map, range and opacity from the controls. Slice, isosurface, vector and marker layers share the same scene and camera, which is what makes model and observation co-visualization a single view rather than two panels. A capability check runs first so an unsupported browser gets a clear message and a 2D WMS fallback instead of a blank canvas.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 380, "rankSpacing": 40, "nodeSpacing": 30}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    IN["INPUT GATE<br/>Volume, slice, mesh, vectors,<br/>markers, plus display settings"]:::gate
    P["STAGE PLATFORM<br/>Three.js on WebGL2<br/>runs in the user browser"]:::plat
    M0["WEBGL2 CAPABILITY CHECK<br/>In: browser context<br/>Does: test WebGL2 and 3D texture<br/>Out: proceed or fall back"]:::mod
    M1["SCENE MANAGER<br/>In: extent, exaggeration factor<br/>Does: camera, orbit controls,<br/>scale depth axis for relief<br/>Out: shared scene and camera"]:::mod
    M2["VOLUME RENDERER<br/>In: volume bytes plus range<br/>Does: upload Data3DTexture,<br/>ray-march, apply colour map,<br/>scale type and opacity<br/>Out: full water column view"]:::mod
    M3["SLICE AND ISOSURFACE LAYER<br/>In: slice array or mesh<br/>Does: textured plane at depth;<br/>BufferGeometry for isosurface<br/>Out: slice and surface meshes"]:::mod
    M4["VECTOR LAYER<br/>In: positions plus u,v<br/>Does: instanced arrows oriented<br/>to current direction<br/>Out: current vector field"]:::mod
    M5["OBSERVATION OVERLAY<br/>In: marker positions<br/>Does: instanced markers at<br/>lat, lon, depth; raycast picking<br/>Out: markers plus click events"]:::mod
    F["RENDER FALLBACK<br/>WebGL2 unavailable<br/>Show message, load 2D WMS<br/>layer from S5 GeoServer"]:::fail
    OUT["OUTPUT GATE<br/>One combined 3D view plus<br/>instrument selection events"]:::out

    IN --> P --> M0
    M0 -->|"supported"| M1
    M0 -->|"unsupported"| F
    M1 --> M2
    M1 --> M3
    M2 --> M4
    M3 --> M5
    M4 --> OUT
    M5 --> OUT

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef plat fill:#F1F5F9,stroke:#64748B,color:#1F2937;
    classDef fail fill:#FFE4E6,stroke:#BE123C,color:#1F2937;
```

### 8. S7 User Interface / Interaction

Stage purpose: give the user the controls, and show the profile chart beside the 3D view.

Selected stage solution: React with TypeScript holds all current selections in one view state store, which is the single source of truth. Controls write to it, and both the renderer and the data client read from it, so a variable change and a colour change follow the same path. The store also decides which change needs new data from S5 and which is a local redraw: palette, scale type, opacity and exaggeration stay in the browser, while variable, depth and time step fetch. Plotly draws the depth-versus-variable profile with a reversed depth axis, and it sits next to the scene so model and observation are compared without leaving the page.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 380, "rankSpacing": 40, "nodeSpacing": 30}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    IN["INPUT GATE<br/>Combined 3D view from S6,<br/>catalogue options, user actions"]:::gate
    P["STAGE PLATFORM<br/>React + TypeScript, Vite build<br/>Azure Static Web Apps, global CDN"]:::plat
    M1["CONTROL PANEL<br/>In: catalogue options<br/>Does: variable select, depth<br/>slider, colour palette, min/max,<br/>log or linear, opacity, relief<br/>Out: setting changes"]:::mod
    M2["VIEW STATE STORE<br/>In: setting and click events<br/>Does: hold current selection,<br/>split refetch from local redraw<br/>Out: render state, fetch intent"]:::mod
    M3["DATA CLIENT<br/>In: fetch intent<br/>Does: call S5 catalogue, field<br/>and observation endpoints<br/>Out: arrays, markers, profiles"]:::mod
    M4["ANIMATION CONTROLLER<br/>In: play, pause, step<br/>Does: advance time index and<br/>prefetch the next step<br/>Out: time step sequence"]:::mod
    M5["PROFILE CHART<br/>In: selected instrument series<br/>Does: plot depth versus variable,<br/>depth axis reversed, timestamps<br/>Using: Plotly.js<br/>Out: profile beside the 3D view"]:::mod
    OUT["OUTPUT GATE<br/>Browser-native interactive<br/>visualization with profile"]:::out

    IN --> P --> M1
    M1 --> M2
    M2 --> M3
    M2 --> M4
    M4 --> M3
    M3 --> M5
    M2 -->|"local redraw"| OUT
    M5 --> OUT

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef plat fill:#F1F5F9,stroke:#64748B,color:#1F2937;
```

### 9. Cross-cutting solution decisions

| Concern | Where it is solved | How it is solved |
|---|---|---|
| CF Conventions | S2 NetCDF Parser; S5 OGC Service | xarray opens with `decode_cf` enabled, so time units and packed values resolve on read; GeoServer reads the same CF `grid_mapping` attribute for projection |
| OGC WMS/WCS | S5 OGC Service | GeoServer NetCDF data store points at the curated container and publishes time and elevation dimensions as WMS layers and WCS coverages |
| Scalability | S2, S3, S5 | Container Apps Jobs raise parallelism for backlog; Container Apps scales API replicas on HTTP load; share capacity is a provisioning choice rather than a code change. No numeric target is set, because the SRS states none |
| Extensibility | S2 Source Registry | A new float type, sensor, model variable or ML-derived product is added as one registry entry naming its format, path and column map; parsers and canonical names are unchanged |
| Browser and platform independence | S6, S7 | Static Web Apps serves plain HTML, CSS and JavaScript over a global CDN with free SSL; rendering uses the browser's own WebGL2, so nothing is installed on the client |
| Azure deployment and INCOIS portability | All stages | Every server-side part is a container image or a standard service. On INCOIS hardware, FastAPI and GeoServer run as the same containers, the Azure Files share is replaced by any POSIX or NFS mount behind the same path convention, PostgreSQL with PostGIS installs directly, and Static Web Apps is replaced by any static web server |

### 10. Decision record

Each row is a decision that shaped the design, the force behind it, what it costs, and the signal that should make the team reopen it. Status is Accepted for all seven; none is pending.

| Decision | Why | Consequence | Revisit when |
|---|---|---|---|
| D1. Curated grids live on an Azure Files share, not ADLS Gen2 | GeoServer reads NetCDF from a filesystem path, and Container Apps mounts Azure Files but explicitly not Blob Storage. On ADLS Gen2 the OGC requirement could not be served at all | One storage system instead of two, and both containers see ordinary paths. Share capacity becomes a provisioning decision rather than an elastic one | Grid volume outgrows one share, or OGC moves to a host that can mount blob storage |
| D2. Data stays as native CF NetCDF, with no derived or tiled format | xarray and GeoServer both read CF NetCDF directly, so ingestion needs no conversion step and there is a single copy of the truth | No format code to write or keep in sync, but every view is computed from the source file at request time with no precomputed shortcut | Repeated requests for the same variable and time make request-time computation the bottleneck |
| D3. Grids as files, observations in PostgreSQL with PostGIS | Gridded arrays and point observations have opposite access patterns: slice by coordinate versus filter by map extent | Marker queries get a real spatial index and grids are not forced into rows, at the cost of operating two stores | Observation volume needs partitioning, or profiles start being served from files |
| D4. S4 processing runs inside the S5 API container | One fewer deployment for a small team, and a view request stays a single hop | Marching cubes and volume resampling share a process and a scaling signal with light catalogue lookups, so one heavy request affects scaling for everything | Isosurface or volume requests start delaying catalogue and observation responses |
| D5. GeoServer serves OGC rather than WMS/WCS being built into FastAPI | WMS and WCS are large specifications, and GeoServer's NetCDF store already exposes time and elevation dimensions | A second container and its configuration to learn, in exchange for not implementing two OGC specifications | Only a narrow, fixed subset of WMS is ever actually used |
| D6. Three.js on WebGL2 for rendering | Volume rendering needs a 3D texture, which WebGL2 provides through Data3DTexture and WebGL1 does not. The SRS named Three.js among its options without selecting one | Browsers without WebGL2 cannot render the volume, which is why S6 carries a capability check and a 2D WMS fallback | A globe-shaped view matters more than volumetric depth, which is where Cesium.js would be reconsidered |
| D7. A Source Registry entry is the extensibility mechanism | EXT-001 asks for new sources and variables with minimal code change, and a declarative entry per feed leaves parsers and canonical names untouched | Adding a source becomes configuration, but the registry turns into a contract that every later stage depends on | A new sensor needs a reader that no existing parser covers |

### 11. Requirement coverage

| SRS IDs | Stage and module |
|---|---|
| DIR-001 to DIR-003 | S2 NetCDF Parser; S3 Curated Grid Store and Dataset Catalogue |
| DIR-004 to DIR-006 | S2 Source Adapter, Delimited Text Parser, Canonical Field Mapper; S3 Observation Store |
| DIR-007, ING-001, ING-002 | S2 NetCDF Parser and Delimited Text Parser |
| STD-001 | S2 NetCDF Parser, CF decoding on read |
| BDA-001 | S5 Catalogue API, Field Data API, Observation API |
| STD-002, STD-003 | S5 OGC Service on GeoServer |
| MVR-001, MVR-002 | S4 Volume Builder; S6 Volume Renderer |
| MVR-003 | S4 Level Extractor; S6 Slice and Isosurface Layer |
| MVR-004 | S4 Isosurface Generator; S6 Slice and Isosurface Layer |
| MVR-005 | S4 Model Subsetter; S7 Animation Controller |
| MVR-006 | S4 Level Extractor, u and v sampling; S6 Vector Layer |
| IDO-001, IDO-002 | S6 Observation Overlay, instanced markers with raycast picking |
| IDO-003 | S4 Profile Builder; S5 Observation API; S7 Profile Chart |
| UIC-001 to UIC-003 | S7 Control Panel and Animation Controller; S4 Level Extractor; S5 Catalogue API |
| UIC-004 to UIC-006 | S7 Control Panel; S6 Volume Renderer shader uniforms |
| UIC-007 | S7 Control Panel; S6 Scene Manager depth-axis scale |
| MOI-001 to MOI-003 | S6 Scene Manager and Observation Overlay in one scene; S7 Profile Chart beside the view |
| WEB-001, WEB-002 | S6 browser WebGL2; S7 Static Web Apps delivery |
| WEB-003 | All server-side stages containerised; see cross-cutting row on portability |
| WEB-004 | S2 Job parallelism; S3 share capacity; S5 Container Apps replicas |
| EXT-001 to EXT-003 | S2 Source Registry entry per new source, sensor, variable or ML product |

All 39 active SRS IDs are covered. No requirement ID has been invented.

### 12. Practical build order

1. Create the Azure Files share with raw/, curated/ and rejected/ folders, and the PostgreSQL Flexible Server with PostGIS enabled. Land one real model NetCDF and one Argo file by hand.
2. Build the S2 ingestion container: Source Registry, both parsers, Canonical Field Mapper, Catalogue Writer. Run it locally until one model run and one instrument batch appear in the curated store and the catalogue.
3. Build the S5 FastAPI service with the Catalogue API and Observation API only, reading the tables from step 2. Confirm the generated OpenAPI page lists them.
4. Add S4 Model Subsetter and Volume Builder, then expose them through the Field Data API. At this point one variable at one time step can be fetched as a volume.
5. Build the S6 scene: capability check, Scene Manager, Volume Renderer. Getting one volume on screen is the highest-risk step, so do it before any other view.
6. Add the Level Extractor and Isosurface Generator with their S6 layers, then the Observation Overlay with click picking.
7. Build S7 controls, view state store and Plotly profile chart, then deploy: Container Apps Job for S2, Container Apps for S5 and GeoServer, Static Web Apps for S7.

### 13. Technology basis

Official documentation used to validate the selected technologies.

- xarray, NetCDF reading with CF decoding, lazy loading and coordinate selection: https://docs.xarray.dev/en/stable/user-guide/io.html
- three.js Data3DTexture, 3D textures for volume rendering: https://threejs.org/docs/#api/en/textures/Data3DTexture
- GeoServer NetCDF data store, time and elevation dimensions, CF grid mapping: https://docs.geoserver.org/stable/en/user/extensions/netcdf/netcdf.html
- GeoServer NetCDF output format for WCS 2.0.1 coverages: https://docs.geoserver.org/stable/en/user/extensions/netcdf-out/index.html
- FastAPI features, Pydantic validation and generated OpenAPI docs: https://fastapi.tiangolo.com/features/
- Azure Container Apps Jobs, manual, schedule and event triggers for finite tasks: https://learn.microsoft.com/en-us/azure/container-apps/jobs
- Azure Static Web Apps, React hosting, global distribution, free SSL and custom domains: https://learn.microsoft.com/en-us/azure/static-web-apps/overview
- Azure Container Apps storage mounts, which support Azure Files but explicitly not Blob Storage, and therefore decide where curated NetCDF must live: https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts
- PostGIS availability on Azure Database for PostgreSQL flexible server: https://learn.microsoft.com/en-us/azure/postgresql/extensions/concepts-extensions-versions
