// The S7 data client: semantic requests in, typed results out.
//
// Feature modules depend on the DataClient interface only; HttpDataClient is
// the one binding to S5's HTTP surface and is chosen in main.tsx.
/** A failure the user can act on, carrying S5's stable code. */
export class ServiceError extends Error {
    code;
    constructor(code, message) {
        super(message);
        this.code = code;
    }
}
export class HttpDataClient {
    fetchImpl;
    pollIntervalMs;
    constructor(fetchImpl = (...args) => fetch(...args), pollIntervalMs = 500) {
        this.fetchImpl = fetchImpl;
        this.pollIntervalMs = pollIntervalMs;
    }
    async catalogue(signal) {
        const body = await this.json("/api/v1/catalogue", { signal });
        // The model half stands on its own; an observation outage is coded.
        const down = body.observation_failure != null || body.observation_versions == null;
        return { versions: body.versions, observations: down ? null : body.observation_versions ?? null };
    }
    observationMarkers(query, signal) {
        const params = new URLSearchParams(Object.entries(query).map(([k, v]) => [k, String(v)]));
        return this.json(`/api/v1/observation-markers?${params}`, { signal });
    }
    observationProfile(query, signal) {
        const params = new URLSearchParams({
            dataset_version_id: query.dataset_version_id, platform_id: query.platform_id, cycle: query.cycle,
        });
        for (const variable of query.variables)
            params.append("variables", variable);
        return this.json(`/api/v1/observation-profiles?${params}`, { signal });
    }
    async pointField(intent, signal) {
        let view = (await this.json("/api/v1/point-fields", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(intent),
            signal,
        }));
        // An asynchronous executor accepts first and finishes later.
        while (!view.finished) {
            await delay(this.pollIntervalMs, signal);
            view = (await this.json(view.links.self, { signal }));
        }
        return view;
    }
    async productData(url, signal) {
        const response = await this.fetchImpl(url, { signal });
        if (!response.ok)
            throw await serviceError(response);
        return response.arrayBuffer();
    }
    async json(url, init) {
        const response = await this.fetchImpl(url, init);
        if (!response.ok)
            throw await serviceError(response);
        return response.json();
    }
}
async function serviceError(response) {
    try {
        const body = await response.json();
        const detail = body?.detail;
        if (detail && typeof detail.code === "string") {
            return new ServiceError(detail.code, String(detail.message ?? detail.code));
        }
        if (Array.isArray(detail)) {
            return new ServiceError("invalid_request", "the request was not understood by the server");
        }
    }
    catch { /* not JSON */ }
    return new ServiceError("service_unavailable", `the server answered ${response.status}`);
}
function delay(ms, signal) {
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
