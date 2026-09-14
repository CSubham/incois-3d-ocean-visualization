## Low-Level Design and Solution Document

INCOIS 3D Ocean Data Visualization System
Problem Statement ID: 26067
Requirements authority: SRS_Technical_Requirements_Mapping.txt
Architecture authority: HLSA_INCOIS_3D_Ocean_Data_Visualization_System.md
Purpose: define the actual solution modules inside each pipeline stage, how each module works, which technology implements it, and what it hands to the next stage.
Audience: student development team building the system end to end.
Status: INCOMPLETE — under active revision. Not an approved basis for implementation.

The seven-stage pipeline is fixed by the HLSA and is preserved here. This document adds module-level solution detail and selected technology. It does not change any requirement or stage boundary.

### 1. Overall selected solution

Ingestion and processing use Python, xarray and pandas. NetCDF interpretation uses CF-aware decoding and a separate conformance check. Managed scientific data is accessed through a storage adapter, while searchable catalogue and profile information uses PostgreSQL with PostGIS. Expensive visualization preparation runs in a separate Python worker so FastAPI remains a lightweight data-serving boundary. The standards route will reuse an existing INCOIS service or GeoServer only after the selected NetCDF is proven through WMS and WCS requests. The browser uses Three.js on WebGL2 for rendering and React with TypeScript and Plotly for interaction and profiles.

The selected Azure profile uses Container Apps Jobs for finite ingestion runs, separate Container Apps for the processing worker and FastAPI, Static Web Apps for the browser bundle, PostgreSQL Flexible Server with PostGIS, and ADLS Gen2 as the scientific-store candidate. Azure Files is used only if the selected standards server requires a mounted read-only publication view. The final storage backend and standards server remain explicit decision gates until the INCOIS environment and representative dataset are confirmed.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 380, "rankSpacing": 40, "nodeSpacing": 30}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    S1["S1 DATA SOURCES<br/>External model and observation data<br/>NetCDF and delimited text"]:::ext
    S2["S2 DATA INGESTION<br/>Python, xarray, pandas<br/>Azure: Container Apps Jobs"]:::proc
    S3["S3 DATA STORAGE / MANAGEMENT<br/>Storage adapter + PostgreSQL/PostGIS<br/>Azure candidate: ADLS Gen2"]:::store
    S4["S4 DATA PROCESSING<br/>Separate Python worker<br/>Azure: Container Apps"]:::proc
    S5["S5 BACKEND / SERVING<br/>FastAPI + conditional OGC route<br/>Azure: Container Apps"]:::serve
    S6["S6 3D RENDERING<br/>Three.js on WebGL2<br/>Runs in the user browser"]:::client
    S7["S7 USER INTERFACE<br/>React, TypeScript, Plotly<br/>Azure: Static Web Apps"]:::client
    PORT["EXTERNAL OCEAN PORTALS<br/>National and international"]:::ext

    S1 -->|"source data"| S2
    S2 -->|"accepted data"| S3
    S3 -->|"managed data"| S4
    S4 -->|"prepared products"| S5
    S5 -->|"served model and markers"| S6
    S6 -->|"combined view and pick events"| S7
    S7 -.->|"data requests"| S5
    S7 -.->|"local display controls"| S6
    S5 -.->|"preparation request"| S4
    S3 -.->|"read-only catalogue and<br/>standards publication reference"| S5
    PORT ---|"OGC WMS/WCS interoperability<br/>direction unresolved"| S5

    classDef ext fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef proc fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef store fill:#EDE9FE,stroke:#6D28D9,color:#1F2937;
    classDef serve fill:#FFEDD5,stroke:#C2410C,color:#1F2937;
    classDef client fill:#ECFDF5,stroke:#059669,color:#0F172A;
```

### 2. S1 Data Sources

Stage purpose: identify the external data and source context available to the system.

Selected stage solution: S1 remains outside the system boundary. It supplies retrievable model datasets and observation records through provider endpoints, files or documented uploads. It performs no internal acquisition, transformation or storage. Provider identity, access method and source-supplied time or observation-mode context cross the boundary with the data. Internal connector and registry responsibilities begin in S2.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 380, "rankSpacing": 40, "nodeSpacing": 30}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    IN["INPUT GATE<br/>Existing provider-held<br/>ocean data"]:::gate
    M1["MODEL DATA SOURCES<br/>In: numerical model outputs<br/>Responsibility: expose supported<br/>fields across depth, grid and time<br/>Out: retrievable NetCDF data"]:::mod
    M2["OBSERVATION DATA SOURCES<br/>In: Argo, Glider, CTD and BGC<br/>Responsibility: expose observations<br/>with source-supplied context<br/>Out: NetCDF or delimited data"]:::mod
    OUT["OUTPUT GATE TO S2<br/>Provider endpoint or file<br/>Source identity and access context<br/>Real-time/delayed mode when supplied"]:::out

    IN --> M1
    IN --> M2
    M1 --> OUT
    M2 --> OUT

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
```

### 3. S2 Data Ingestion

Stage purpose: acquire or accept supported source data, parse it, validate it and prepare an accepted handoff to S3.

Selected stage solution: a Python ingestion container can run manually, on a schedule or from an approved source trigger. A Source Connector uses the registry to retrieve or accept data and selects a registered NetCDF or delimited-text adapter. xarray decodes packed values, time and coordinates; cf-xarray assists semantic discovery; and an IOOS Compliance Checker run plus project semantic checks validates NetCDF separately from decoding. Delimited text is validated against its registered source schema. The mapper preserves original names while identifying temperature, salinity, chlorophyll, eastward and northward current components, coordinates, units and exact observation/profile identity. S2 performs no durable catalogue or curated-store write itself.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 380, "rankSpacing": 40, "nodeSpacing": 30}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    IN["INPUT GATE FROM S1<br/>Provider endpoint or file<br/>Source identity and context"]:::gate
    P["STAGE PLATFORM<br/>Python ingestion container<br/>xarray, cf-xarray, pandas<br/>IOOS Compliance Checker"]:::plat
    M1["SOURCE CONNECTOR AND REGISTRY<br/>In: source identity and access context<br/>Responsibility: retrieve or accept data;<br/>select a registered adapter<br/>Out: source data plus adapter definition"]:::mod
    M2["NETCDF ADAPTER<br/>In: NetCDF data<br/>Responsibility: CF-aware decode;<br/>discover dimensions and variables<br/>Out: decoded data plus metadata"]:::mod
    M3["DELIMITED-TEXT ADAPTER<br/>In: ASCII or delimited observations<br/>Responsibility: parse registered schema;<br/>retain source field meanings<br/>Out: typed observation records"]:::mod
    M4["VALIDATOR AND SEMANTIC MAPPER<br/>In: decoded data or typed records<br/>Responsibility: validate convention/schema;<br/>map fields without destroying source names<br/>Out: accepted data, manifest and profiles"]:::mod
    F["REJECTED HANDOFF<br/>Validation failed<br/>Out: source reference and reason<br/>Not visible as accepted data"]:::fail
    OUT["OUTPUT GATE TO S3<br/>Accepted values, units and masks<br/>Horizontal and vertical coordinates<br/>Time context, source identity and mode<br/>Validation manifest and profiles"]:::out

    IN --> M1
    P -.->|"hosts ingestion modules"| M1
    M1 --> M2
    M1 --> M3
    M2 --> M4
    M3 --> M4
    M4 -->|"accepted"| OUT
    M4 -->|"invalid"| F

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef plat fill:#F1F5F9,stroke:#64748B,color:#1F2937;
    classDef fail fill:#FFE4E6,stroke:#BE123C,color:#1F2937;
```

### 4. S3 Data Storage / Management

Stage purpose: own durable scientific data, catalogue visibility and observation/profile records for downstream use.

Selected stage solution: accepted scientific data is held through a deployment-neutral Scientific Object Store interface. PostgreSQL stores dataset, variable and provenance catalogue information; PostGIS supports spatial lookup of instruments and profiles. Native accepted NetCDF remains preserved. For Azure, Blob/ADLS is the scientific-store candidate. A read-only Azure Files publication view is created only if the selected standards server requires mounted files. The final backend remains conditional on INCOIS infrastructure.

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 380, "rankSpacing": 40, "nodeSpacing": 30}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    IN["INPUT GATE FROM S2<br/>Accepted scientific data<br/>Manifest and profile records"]:::gate
    P["STAGE PLATFORM<br/>Scientific storage adapter<br/>PostgreSQL with PostGIS<br/>Conditional publication view"]:::plat
    M1["SCIENTIFIC OBJECT STORE<br/>In: accepted scientific data<br/>Responsibility: preserve versioned data<br/>and return stable managed references<br/>Out: scientific object reference"]:::mod
    M2["OBSERVATION / PROFILE STORE<br/>In: profile records and source mode<br/>Responsibility: retain identity, position,<br/>time, variables and spatial lookup<br/>Out: queryable marker and profile data"]:::mod
    M3["DATASET CATALOGUE<br/>In: manifest and managed references<br/>Responsibility: record variables, units,<br/>grid, depth, time, extent and readiness<br/>Out: discoverable managed dataset"]:::mod
    OUT["OUTPUT GATE TO S4<br/>Stable managed references<br/>Values, masks and variable units<br/>Grid/CRS, vertical and time descriptors<br/>Exact observation/profile identity"]:::out

    IN --> M1
    IN --> M2
    P -.->|"hosts storage modules"| M1
    P -.->|"hosts storage modules"| M2
    M1 --> M3
    M2 --> M3
    M3 --> OUT

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef plat fill:#F1F5F9,stroke:#64748B,color:#1F2937;
```

### 5. S4 Data Processing

Stage purpose: prepare an independent, scientifically valid product for the requested model or observation view.

Selected stage solution: S5 validates a visualization or profile request and sends the preparation request to S4. A shared Python processing library reads the managed dataset or profile information from S3. Bounded metadata and profile preparation may execute synchronously, while expensive volume resampling and isosurface work runs in a separate worker process. The Scientific Subsetter preserves decoded floating-point values, signed current components, coordinates, units and the missing-data mask. Volume, slice, vector and isosurface builders are independent branches; none consumes the quantized output of another branch. Regridding occurs only when the selected source grid requires a tested transformation.

#### Model product preparation

```mermaid
%%{init: {"layout": "elk", "flowchart": {"wrappingWidth": 300, "rankSpacing": 35, "nodeSpacing": 20}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    REQ["INPUT GATE FROM S5<br/>Validated model-product request<br/>Variable, time, depth and extent"]:::gate
    DATA["INPUT GATE FROM S3<br/>Managed model data<br/>Grid and variable descriptors"]:::gate
    M1["SCIENTIFIC SUBSETTER<br/>In: model request and managed data<br/>Responsibility: select region, time,<br/>depth and variable while retaining<br/>float values, coordinates and mask<br/>Using: Python, xarray and NumPy<br/>Out: decoded scientific subset"]:::mod
    subgraph PRODUCTS["INDEPENDENT MODEL PRODUCT BUILDERS"]
        direction TB
        subgraph SCALAR["SCALAR FIELD PRODUCTS"]
            direction LR
            M2["VOLUME PRODUCT BUILDER<br/>In: decoded scalar subset<br/>Responsibility: prepare full-water-column<br/>volume with explicit delivery encoding<br/>Using: Python and NumPy<br/>Out: volume, range and mask"]:::mod
            M3["DEPTH-SLICE PRODUCT BUILDER<br/>In: decoded scalar subset and depth<br/>Responsibility: select or interpolate<br/>on the scientific grid<br/>Using: xarray and NumPy<br/>Out: slice values, plane coordinates, mask"]:::mod
        end
        subgraph GEOMETRY["VECTOR AND SURFACE PRODUCTS"]
            direction LR
            M4["CURRENT-VECTOR PRODUCT BUILDER<br/>In: signed eastward/northward components<br/>Responsibility: align masks and apply<br/>recorded sampling for display<br/>Using: xarray and NumPy<br/>Out: positions, signed vectors and units"]:::mod
            M5["ISOSURFACE PRODUCT BUILDER<br/>In: float scalar values, physical threshold,<br/>spacing and mask<br/>Responsibility: extract surface geometry<br/>Using: scikit-image and NumPy<br/>Out: mesh, normals and transform"]:::mod
        end
        SCALAR ~~~ GEOMETRY
    end
    F["UNSUPPORTED OR INVALID<br/>Unavailable variable, grid,<br/>depth or time<br/>Out: failure reason to S5"]:::fail
    OUT["OUTPUT GATE TO S5<br/>Independent model product<br/>Units, range, mask, grid/CRS,<br/>vertical/time context and transform"]:::out

    REQ --> M1
    DATA --> M1
    M1 --> SCALAR
    M1 --> GEOMETRY
    M1 -- "invalid or unsupported" --> F
    SCALAR --> OUT
    GEOMETRY --> OUT

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef fail fill:#FFE4E6,stroke:#BE123C,color:#1F2937;
    style PRODUCTS fill:#FFFBEB,stroke:#D6A94C,stroke-width:1px
    style SCALAR fill:#FFFFFF,stroke:#D6A94C,stroke-width:1px
    style GEOMETRY fill:#FFFFFF,stroke:#D6A94C,stroke-width:1px
```

#### Observation and profile preparation

```mermaid
%%{init: {"layout": "elk", "flowchart": {"wrappingWidth": 300, "rankSpacing": 35, "nodeSpacing": 20}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    REQ["INPUT GATE FROM S5<br/>Marker query or exact<br/>instrument/profile identity"]:::gate
    DATA["INPUT GATE FROM S3<br/>Managed observation records<br/>Position, time, variables and mode"]:::gate
    M6["OBSERVATION PRODUCT BUILDER<br/>In: query or exact profile identity<br/>Responsibility: prepare geospatial markers<br/>or depth-versus-variable series<br/>Using: Python processing library<br/>Out: markers or profile with timestamps"]:::mod
    F["NOT FOUND OR UNSUPPORTED<br/>Out: explicit reason to S5"]:::fail
    OUT["OUTPUT GATE TO S5<br/>Markers with exact identity<br/>or profile values, depths and timestamps"]:::out

    REQ --> M6
    DATA --> M6
    M6 --> OUT
    M6 -- "not found or unsupported" --> F

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef fail fill:#FFE4E6,stroke:#BE123C,color:#1F2937;
```

### 6. S5 Backend / Data Serving

Stage purpose: expose prepared data to the browser and publish standards-based services to external portals.

Selected stage solution: FastAPI validates browser requests and coordinates preparation through S4. It returns catalogue choices and selected profiles to S7, while model products and geospatial markers go to S6. S5 reads S3 only for catalogue metadata and the standards publication reference; browser visualization products still pass through S4. These are parallel serving responsibilities, not a processing sequence. The OGC route is separate from the browser API. Existing INCOIS THREDDS and GeoServer remain candidates until one is proven to serve the representative NetCDF correctly through both WMS and WCS; the LLD does not implement those standards itself.

#### Browser request and serving path

```mermaid
%%{init: {"layout": "elk", "flowchart": {"wrappingWidth": 300, "rankSpacing": 35, "nodeSpacing": 20}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    BIN["INPUT GATE FROM S7<br/>Catalogue, model, marker<br/>or exact profile request"]:::gate
    SIN["READ-ONLY INPUT FROM S3<br/>Dataset and variable catalogue"]:::gate
    PREP["INPUT GATE FROM S4<br/>Prepared model, markers,<br/>profile or explicit failure"]:::gate
    subgraph PATHS["PARALLEL BROWSER API RESPONSIBILITIES"]
        direction TB
        subgraph CONTROL["REQUEST AND DISCOVERY"]
            direction LR
            M1["REQUEST COORDINATOR<br/>In: browser request<br/>Responsibility: validate selection<br/>and request required preparation<br/>Using: FastAPI<br/>Out: validated request to S4"]:::mod
            M2["CATALOGUE RESPONSE<br/>In: dataset descriptors<br/>Responsibility: expose datasets,<br/>variables, depths and time steps<br/>Using: FastAPI<br/>Out: options for S7"]:::mod
        end
        subgraph DELIVERY["PREPARED DATA DELIVERY"]
            direction LR
            M3["VISUALIZATION RESPONSE<br/>In: prepared model product<br/>Responsibility: deliver product with<br/>scientific descriptor and failure state<br/>Using: FastAPI<br/>Out: browser-readable data for S6"]:::mod
            M4["OBSERVATION / PROFILE RESPONSE<br/>In: prepared markers or profile<br/>Responsibility: deliver positions or<br/>depth-versus-variable series<br/>Using: FastAPI<br/>Out: markers for S6 or profile for S7"]:::mod
        end
        CONTROL ~~~ DELIVERY
    end
    TO4["OUTPUT GATE TO S4<br/>Validated preparation request"]:::out
    BOUT6["OUTPUT GATE TO S6<br/>Model product or markers<br/>with scientific descriptor"]:::out
    BOUT7["OUTPUT GATE TO S7<br/>Catalogue choices, selected profile<br/>or explicit failure"]:::out

    BIN --> M1
    SIN --> M2
    PREP --> M3
    PREP --> M4
    M1 --> TO4
    M2 --> BOUT7
    M3 --> BOUT6
    M4 -- "markers" --> BOUT6
    M4 -- "profile" --> BOUT7

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    style PATHS fill:#FFFBEB,stroke:#D6A94C,stroke-width:1px
    style CONTROL fill:#FFFFFF,stroke:#D6A94C,stroke-width:1px
    style DELIVERY fill:#FFFFFF,stroke:#D6A94C,stroke-width:1px
```

#### Portal standards path

```mermaid
%%{init: {"layout": "elk", "flowchart": {"wrappingWidth": 300, "rankSpacing": 35, "nodeSpacing": 20}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    PIN["INPUT GATE FROM PORTAL<br/>WMS or WCS request"]:::gate
    SIN["READ-ONLY INPUT FROM S3<br/>Tested standards publication reference"]:::gate
    M5["OGC STANDARDS ROUTE<br/>In: request and tested publication<br/>Responsibility: delegate to the selected<br/>conforming standards service<br/>Using: proven INCOIS service or GeoServer<br/>Out: standards response"]:::mod
    POUT["OUTPUT GATE TO PORTAL<br/>WMS or WCS response"]:::out

    PIN --> M5
    SIN --> M5
    M5 --> POUT

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
```

### 7. S6 3D Rendering / Visualization

Stage purpose: draw the model field and the instrument markers together in one interactive 3D scene.

Selected stage solution: Three.js on WebGL2 is selected for the first rectilinear-grid prototype. A capability check verifies the required browser support before rendering. The Scene Manager converts every product and marker through one documented local coordinate transform, retains physical units and applies vertical exaggeration only as a reversible display transform. Volume, slice, isosurface, vector and observation layers are parallel scene layers. The volume payload may use a tested typed encoding with an explicit mask; it is not assumed to be 8-bit. An unsupported browser or product receives a clear unsupported state rather than a blank canvas.

```mermaid
%%{init: {"layout": "elk", "flowchart": {"wrappingWidth": 300, "rankSpacing": 35, "nodeSpacing": 20}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    IN1["INPUT GATE A FROM S5<br/>Volume, slice, mesh, vectors<br/>or geospatial markers<br/>with scientific descriptor"]
    IN2["INPUT GATE B FROM S7<br/>Palette, physical range, scale,<br/>opacity and vertical exaggeration"]
    M0["WEBGL2 CAPABILITY CHECK<br/>In: browser context<br/>Responsibility: test WebGL2<br/>and required texture support<br/>Using: browser WebGL2 API<br/>Out: proceed or unsupported state"]
    M1["SCENE AND COORDINATE MANAGER<br/>In: product transform and display state<br/>Responsibility: shared camera, local frame<br/>and reversible depth exaggeration<br/>Using: Three.js on WebGL2<br/>Out: common scene context"]
    subgraph LAYERS["PARALLEL SCENE LAYERS"]
        direction TB
        subgraph SCALAR_LAYERS["SCALAR FIELD LAYERS"]
            direction LR
            M2["VOLUME RENDERER<br/>In: volume, range and mask<br/>Responsibility: upload typed texture,<br/>ray-march and apply transfer settings<br/>Using: Three.js on WebGL2<br/>Out: full-water-column view"]
            M3["SLICE / ISOSURFACE LAYERS<br/>In: physical slice or surface mesh<br/>Responsibility: place geometry using<br/>the shared scene transform<br/>Using: Three.js on WebGL2<br/>Out: slice or surface view"]
        end
        subgraph OVERLAY_LAYERS["VECTOR AND OBSERVATION LAYERS"]
            direction LR
            M4["VECTOR LAYER<br/>In: positions plus signed u,v<br/>Responsibility: orient sampled arrows<br/>to current direction<br/>Using: Three.js on WebGL2<br/>Out: current vector field"]
            M5["OBSERVATION OVERLAY<br/>In: marker positions and exact identity<br/>Responsibility: place geospatial markers<br/>and resolve marker selection<br/>Using: Three.js on WebGL2<br/>Out: markers plus exact pick event"]
        end
        SCALAR_LAYERS ~~~ OVERLAY_LAYERS
    end
    F["UNSUPPORTED STATE<br/>Required browser capability<br/>or product support unavailable<br/>Out: clear reason to S7"]
    OUT2["OUTPUT GATE B TO S7<br/>Exact marker/profile selection event"]
    OUT1["OUTPUT GATE A TO S7<br/>Combined interactive 3D view"]

    IN1 --> M0
    IN2 --> M1
    M0 -- "supported" --> M1
    M0 -- "unsupported" --> F
    M1 --> SCALAR_LAYERS
    M1 --> OVERLAY_LAYERS
    SCALAR_LAYERS --> OUT1
    OVERLAY_LAYERS --> OUT1
    M5 --> OUT2

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef plat fill:#F1F5F9,stroke:#64748B,color:#1F2937;
    classDef fail fill:#FFE4E6,stroke:#BE123C,color:#1F2937;
    class IN1 gate;
    class IN2 gate;
    class M0 mod;
    class M1 mod;
    class M2 mod;
    class M3 mod;
    class M4 mod;
    class M5 mod;
    class F fail;
    class OUT2 out;
    class OUT1 out;
    style LAYERS fill:#FFFBEB,stroke:#D6A94C,stroke-width:1px
    style SCALAR_LAYERS fill:#FFFFFF,stroke:#D6A94C,stroke-width:1px
    style OVERLAY_LAYERS fill:#FFFFFF,stroke:#D6A94C,stroke-width:1px
```

### 8. S7 User Interface / Interaction

Stage purpose: give the user the controls, and show the profile chart beside the 3D view.

Selected stage solution: React with TypeScript holds the current user selection and display state. Changes to dataset, variable, depth or time create a data request to S5. Palette, value range, linear or logarithmic scale, opacity and vertical exaggeration are sent directly to S6 as local display controls. A pick event from S6 carries the exact instrument/profile identity; S7 requests that profile from S5 and Plotly displays depth versus the selected variable with timestamps beside the 3D scene.

```mermaid
%%{init: {"layout": "elk", "flowchart": {"wrappingWidth": 300, "rankSpacing": 35, "nodeSpacing": 20}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
    USER["INPUT GATE A<br/>User selections, controls,<br/>playback and marker actions"]
    RENDER["INPUT GATE C FROM S6<br/>Combined 3D view<br/>or exact pick event"]
    SERVER["INPUT GATE B FROM S5<br/>Catalogue choices, selected profile<br/>or explicit failure"]
    M1["CONTROL PANEL<br/>In: choices and user actions<br/>Responsibility: expose required<br/>selection and display controls<br/>Using: React with TypeScript<br/>Out: state change"]
    M4["ANIMATION CONTROLLER<br/>In: play, pause or step<br/>Responsibility: advance available<br/>model time steps<br/>Using: React with TypeScript<br/>Out: next time selection"]
    M2["VIEW STATE<br/>In: state change or exact pick<br/>Responsibility: keep current selection;<br/>separate server requests from local controls<br/>Using: TypeScript state module<br/>Out: request intent or display settings"]
    M3["DATA CLIENT<br/>In: request intent and S5 response<br/>Responsibility: exchange catalogue<br/>and exact profile information<br/>Using: TypeScript web client<br/>Out: request, choices or profile"]
    TO6["OUTPUT GATE TO S6<br/>Local palette, range and scale<br/>opacity or vertical exaggeration"]
    TO5["OUTPUT GATE TO S5<br/>Catalogue, model, marker<br/>or exact profile request"]
    M5["PROFILE CHART<br/>In: selected profile and timestamps<br/>Responsibility: plot depth versus variable<br/>beside the displayed model field<br/>Using: Plotly<br/>Out: profile view"]
    OUT["USER-FACING OUTPUT<br/>Browser-native combined 3D view,<br/>controls and selected profile"]

    USER --> M1 --> M2
    RENDER -- "exact pick" --> M2
    M2 -- "server data needed" --> M3
    M2 --> M4
    M4 -- "next time" --> M2
    M3 --> TO5
    SERVER --> M3
    M2 -- "local display settings" --> TO6
    M3 -- "selected profile" --> M5
    RENDER -- "combined 3D view" --> OUT
    M1 --> OUT
    M5 --> OUT

    classDef gate fill:#E8F1FB,stroke:#2563EB,color:#0F172A;
    classDef mod fill:#FFF4D6,stroke:#B7791F,color:#1F2937;
    classDef out fill:#ECFDF5,stroke:#059669,color:#0F172A;
    classDef plat fill:#F1F5F9,stroke:#64748B,color:#1F2937;
    class USER gate;
    class RENDER gate;
    class SERVER gate;
    class M1 mod;
    class M2 mod;
    class M3 mod;
    class M4 mod;
    class M5 mod;
    class TO5 out;
    class TO6 out;
    class OUT out;
```

### 9. Cross-cutting solution decisions

| Concern | Where it is solved | How it is solved |
|---|---|---|
| CF Conventions | S2 NetCDF Adapter and Validator | xarray performs CF-aware decoding; cf-xarray assists semantic discovery; a conformance checker and project checks separately validate required coordinates, units, masks and metadata. CF is not claimed for delimited text. |
| OGC WMS/WCS | S5 conditional standards route | Reuse a conforming INCOIS service where available; otherwise prove GeoServer with the representative NetCDF through both WMS and WCS before selection. |
| Scalability | S2, S3, S4 and S5 | Keep finite ingestion and expensive processing outside the lightweight API, use independently runnable containers, and keep scientific storage behind an adapter. No numeric capacity target is invented. |
| Extensibility | S2 and affected S4 to S7 modules | Known source schemas use registry configuration. A genuinely new format, sensor product or render product uses a registered typed adapter, builder and renderer where needed, without changing unrelated modules. |
| Browser and platform independence | S6 and S7 | Deliver a static HTML, CSS and JavaScript application; execute rendering in a capable browser; show an explicit unsupported state when required WebGL2 capability is absent. |
| Azure deployment and INCOIS portability | Server-side stages and delivery | Package the API, ingestion and processing units as OCI containers, deliver the frontend as static files, and isolate cloud storage behind an adapter. Final storage and hosting are confirmed against INCOIS infrastructure. |

### 10. Decision record

Status distinguishes selected logical design from choices that still require evidence.

| Decision | Status | Reason and boundary |
|---|---|---|
| D1. Access scientific data through a storage adapter; use Blob/ADLS in the Azure profile | Conditional | The logical boundary is fixed. The final backend depends on INCOIS facilities and the selected OGC service. |
| D2. Preserve accepted native NetCDF and build independent delivery products | Accepted logical design | Scientific source values remain recoverable; delivery encoding is tested per product and cannot become the source for another product. |
| D3. Keep scientific arrays in object/file storage and searchable catalogue/profile data in PostgreSQL/PostGIS | Accepted | These data types have different access needs; the storage adapter preserves deployment portability. |
| D4. Run expensive S4 preparation in a worker separate from FastAPI | Accepted | Heavy volume or isosurface work must not consume the lightweight API execution boundary. The job transport is an implementation detail. |
| D5. Reuse an existing conforming INCOIS service or use GeoServer for OGC WMS/WCS | Prototype gate | Select only after both WMS and WCS work with the representative NetCDF. The LLD does not implement either standard. |
| D6. Use Three.js on WebGL2 for the first rectilinear-grid renderer | Conditional | Selection depends on the representative grid and browser capability test; unsupported capability must be shown clearly. |
| D7. Use a registry for known schemas and typed extension modules for new behavior | Accepted | Configuration handles known shapes; a new parser, product or renderer is added only where the extension actually requires it. |

### 11. Requirement coverage

The owner is fixed by the HLSA. Supporting modules implement handoffs without taking ownership from that stage.

| SRS IDs | HLSA owner | Supporting design response |
|---|---|---|
| DIR-001 to DIR-007 | S2 | Source Connector, format adapters, Validator and Semantic Mapper; S3 preserves accepted data and S4 consumes it. |
| ING-001 to ING-002 | S2 | Registered NetCDF and delimited-text adapters perform automated parsing. |
| STD-001 | S2 and cross-cutting | CF-aware decode plus a distinct NetCDF conformance check. |
| BDA-001 | S5 | FastAPI Request Coordinator and parallel catalogue, visualization and observation/profile responses. |
| MVR-001 to MVR-002 | S6 | S4 prepares an independent volume product; S5 serves it; S6 renders the full-water-column view. |
| MVR-003 | S6 | S4 prepares a depth slice and S6 places the slice in the shared scene. |
| MVR-004 | S6 | S4 extracts a mesh from float values and a physical threshold; S6 renders it. |
| MVR-005 | S6 | S7 controls available time steps; S5 obtains each product; S6 replaces the rendered time state. |
| MVR-006 | S6 | S4 retains signed current components and S6 renders vectors alongside supported scalar fields. |
| IDO-001 | S6 | S3 retains observation position and identity; S4 prepares markers; S6 places them through the common transform. |
| IDO-002 to IDO-003 | S7 | S6 returns an exact pick identity; S7 requests and displays the matching Plotly profile with timestamps. |
| UIC-001 to UIC-007 | S7 | Control Panel and View State own the controls; S5 supplies requested data and S6 applies local display settings. |
| MOI-001 | S6 | Model and observation layers share one scene and coordinate transform. |
| MOI-002 to MOI-003 | S7 | The combined scene and selected profile are presented on the same browser page. |
| WEB-001 to WEB-002 | S7 and cross-cutting | Static browser application with no client installation; S6 performs browser-native rendering. |
| WEB-003 to WEB-004 | Cross-cutting | OCI containers, static frontend, storage adapter and separate scalable execution boundaries; no unsupported capacity target. |
| EXT-001 | S2 ingestion aspect and cross-cutting | Registry configuration handles known sources and variables; typed adapters handle genuinely new formats. |
| EXT-002 to EXT-003 | Cross-cutting | Registered adapters, product builders and renderer modules extend only the affected stages. |
| STD-002 to STD-003 | Cross-cutting, served through S5 | A tested conforming service provides WMS/WCS interoperability; service and direction remain evidence-based decisions. |

All 39 active SRS IDs are covered. No requirement ID has been invented.

### 12. Architecture validation order

1. Prove S2 acceptance and rejection with the representative HYCOM model files and genuine Argo, Glider, CTD and BGC fixtures, including real-time and delayed-mode context where supplied.
2. Prove that S3 preserves scientific values and exact profile identity and returns stable managed references without moving ingestion ownership into storage.
3. Prove each S4 product independently from decoded floating-point data, including signed currents, masks, units, coordinates, time and transform metadata.
4. Prove the S7 to S5 to S4 to S5 response loop, then prove both WMS and WCS before selecting the standards service.
5. Prove that S6 aligns model fields and markers in one transform and that every S7 control or exact marker pick reaches the correct destination.
6. Recheck all 39 SRS IDs against observable evidence from the complete browser workflow.

### 13. Technology basis

Official documentation used to validate the selected technologies.

- xarray, NetCDF reading with CF decoding, lazy loading and coordinate selection: https://docs.xarray.dev/en/stable/user-guide/io.html
- cf-xarray, interpretation of CF metadata and coordinate semantics: https://cf-xarray.readthedocs.io/en/latest/
- IOOS Compliance Checker, automated checks for CF and related conventions: https://ioos.github.io/compliance-checker/
- three.js Data3DTexture, 3D textures for volume rendering: https://threejs.org/docs/pages/Data3DTexture.html
- GeoServer NetCDF data store, time and elevation dimensions, CF grid mapping: https://docs.geoserver.org/main/en/user/extensions/netcdf/netcdf/
- GeoServer NetCDF output format for WCS 2.0.1 coverages: https://docs.geoserver.org/main/en/user/extensions/netcdf-out/index.html
- FastAPI features, Pydantic validation and generated OpenAPI docs: https://fastapi.tiangolo.com/features/
- Azure Container Apps Jobs, manual, schedule and event triggers for finite tasks: https://learn.microsoft.com/en-us/azure/container-apps/jobs
- Azure Static Web Apps, React hosting, global distribution, free SSL and custom domains: https://learn.microsoft.com/en-us/azure/static-web-apps/overview
- Azure Data Lake Storage Gen2 and Blob multi-protocol access for the Azure scientific-store candidate: https://learn.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-multi-protocol-access
- Azure Container Apps storage mounts, used only if a selected standards service needs a mounted publication view: https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts
- PostGIS availability on Azure Database for PostgreSQL flexible server: https://learn.microsoft.com/en-us/azure/postgresql/extensions/concepts-extensions-versions
