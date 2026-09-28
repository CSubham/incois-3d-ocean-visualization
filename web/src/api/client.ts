// The S7 data client: semantic requests in, typed results out.
//
// Feature modules depend on the DataClient interface only; HttpDataClient is
// the one binding to S5's HTTP surface and is chosen in main.tsx.

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
  catalogue(signal?: AbortSignal): Promise<CatalogueVersion[]>;
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

  async catalogue(signal?: AbortSignal): Promise<CatalogueVersion[]> {
    const body = await this.json("/api/v1/catalogue", { signal });
    return (body as { versions: CatalogueVersion[] }).versions;
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
