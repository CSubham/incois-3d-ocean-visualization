// The S7 data client: semantic requests in, typed results out.
//
// Feature modules depend on the DataClient interface only; HttpDataClient is
// the one binding to S5's HTTP surface and is chosen in main.tsx.

import type { MarkerDescriptor, ProfileDescriptor } from "./observationWire";
import type { ProductDescriptor } from "./wire";

export interface CatalogueVersion {
  id: string;
  dataset: string;
  geometry: string;
  variables: { name: string; units: string | null }[];
  depth_levels: number;
  time_steps: number;
  extent: {
    time_start: string | null; time_end: string | null;
    depth_min: number | null; depth_max: number | null;
    west: number | null; east: number | null;
    south: number | null; north: number | null;
  };
  // Exact coordinate values, once the catalogue provides them.
  time_values?: string[];
  depth_values?: number[];
  created_at: string;
}

/** An observation dataset version as S3 describes it. */
export interface ObservationVersion {
  dataset_id: string;
  dataset_version_id: string;
  source_id: string;
  geometry: string;
  vertical_coordinate: string;
  vertical_units: string;
  vertical_kind: "depth" | "pressure";
  crs: string;
  vertical_positive: "down" | "up";
  variables: { name: string; units: string | null }[];
  extent: CatalogueVersion["extent"];
  created_at: string;
}

export interface Catalogue {
  versions: CatalogueVersion[];
  /** Null when the observation catalogue could not be read. */
  observations: ObservationVersion[] | null;
}

export interface MarkerQuery {
  dataset_version_id: string;
  west: number; east: number; south: number; north: number;
  time_start: string; time_end: string;
}

export interface ProfileQuery {
  dataset_version_id: string;
  platform_id: string;
  cycle: string;
  variables: string[];
}

export interface PointFieldIntent {
  dataset_version_id: string;
  variable: string;
  time: string;
  west: number; east: number; south: number; north: number;
  depth_minimum: number; depth_maximum: number;
  maximum_points: number;
}

export interface Failure { code: string; message: string }

export interface Budget {
  requested_points: number | null;
  effective_points: number;
  reduced_by_server: boolean;
  maximum_cells: number | null;
}

export interface RequestView {
  request_id: string;
  state: "accepted" | "running" | "succeeded" | "failed";
  finished: boolean;
  failure: Failure | null;
  budget: Budget;
  product: ProductDescriptor | null;
  links: { self: string; data: string };
}

/** A failure the user can act on, carrying S5's stable code. */
export class ServiceError extends Error {
  constructor(readonly code: string, message: string) { super(message); }
}

export interface DataClient {
  catalogue(signal?: AbortSignal): Promise<Catalogue>;
  observationMarkers(query: MarkerQuery, signal?: AbortSignal): Promise<MarkerDescriptor>;
  observationProfile(query: ProfileQuery, signal?: AbortSignal): Promise<ProfileDescriptor>;
  /** Submit and wait until the request finishes, succeeded or failed. */
  pointField(intent: PointFieldIntent, signal?: AbortSignal): Promise<RequestView>;
  productData(url: string, signal?: AbortSignal): Promise<ArrayBuffer>;
}

type Fetch = typeof fetch;

export class HttpDataClient implements DataClient {
  constructor(
    private readonly fetchImpl: Fetch = (...args) => fetch(...args),
    private readonly pollIntervalMs = 500,
  ) {}

  async catalogue(signal?: AbortSignal): Promise<Catalogue> {
    const body = await this.json("/api/v1/catalogue", { signal }) as {
      versions: CatalogueVersion[];
      observation_versions?: ObservationVersion[] | null;
      observation_failure?: { code: string; message: string } | null;
    };
    // The model half stands on its own; an observation outage is coded.
    const down = body.observation_failure != null || body.observation_versions == null;
    return { versions: body.versions, observations: down ? null : body.observation_versions ?? null };
  }

  observationMarkers(query: MarkerQuery, signal?: AbortSignal): Promise<MarkerDescriptor> {
    const params = new URLSearchParams(Object.entries(query).map(([k, v]) => [k, String(v)]));
    return this.json(`/api/v1/observation-markers?${params}`, { signal }) as Promise<MarkerDescriptor>;
  }

  observationProfile(query: ProfileQuery, signal?: AbortSignal): Promise<ProfileDescriptor> {
    const params = new URLSearchParams({
      dataset_version_id: query.dataset_version_id, platform_id: query.platform_id, cycle: query.cycle,
    });
    for (const variable of query.variables) params.append("variables", variable);
    return this.json(`/api/v1/observation-profiles?${params}`, { signal }) as Promise<ProfileDescriptor>;
  }

  async pointField(intent: PointFieldIntent, signal?: AbortSignal): Promise<RequestView> {
    let view = (await this.json("/api/v1/point-fields", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(intent),
      signal,
    })) as RequestView;
    // An asynchronous executor accepts first and finishes later.
    while (!view.finished) {
      await delay(this.pollIntervalMs, signal);
      view = (await this.json(view.links.self, { signal })) as RequestView;
    }
    return view;
  }

  async productData(url: string, signal?: AbortSignal): Promise<ArrayBuffer> {
    const response = await this.fetchImpl(url, { signal });
    if (!response.ok) throw await serviceError(response);
    return response.arrayBuffer();
  }

  private async json(url: string, init: RequestInit): Promise<unknown> {
    const response = await this.fetchImpl(url, init);
    if (!response.ok) throw await serviceError(response);
    return response.json();
  }
}

async function serviceError(response: Response): Promise<ServiceError> {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (detail && typeof detail.code === "string") {
      return new ServiceError(detail.code, String(detail.message ?? detail.code));
    }
    if (Array.isArray(detail)) {
      return new ServiceError("invalid_request", "the request was not understood by the server");
    }
  } catch { /* not JSON */ }
  return new ServiceError("service_unavailable", `the server answered ${response.status}`);
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException("aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(signal.reason ?? new DOMException("aborted", "AbortError"));
    }, { once: true });
  });
}
