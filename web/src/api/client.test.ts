import { describe, expect, it } from "vitest";

import { HttpDataClient, ServiceError, type PointFieldIntent } from "./client";

const intent = {} as PointFieldIntent;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function fakeFetch(responses: Response[]) {
  const calls: string[] = [];
  const impl = (async (url: string) => { calls.push(url); return responses.shift()!; }) as typeof fetch;
  return { calls, impl };
}

describe("HttpDataClient", () => {
  it("polls an asynchronous request until it finishes", async () => {
    const { calls, impl } = fakeFetch([
      json({ finished: false, state: "accepted", links: { self: "/r/1" } }),
      json({ finished: false, state: "running", links: { self: "/r/1" } }),
      json({ finished: true, state: "succeeded", links: { self: "/r/1" } }),
    ]);
    const view = await new HttpDataClient(impl, 1).pointField(intent);
    expect(view.state).toBe("succeeded");
    expect(calls).toEqual(["/api/v1/point-fields", "/r/1", "/r/1"]);
  });

  it("turns S5 failures into coded errors", async () => {
    const coded = new HttpDataClient(fakeFetch([json({ detail: { code: "point_budget", message: "too many" } }, 400)]).impl);
    await expect(coded.pointField(intent)).rejects.toEqual(new ServiceError("point_budget", "too many"));
    const invalid = new HttpDataClient(fakeFetch([json({ detail: [{ loc: ["body"] }] }, 422)]).impl);
    await expect(invalid.pointField(intent)).rejects.toMatchObject({ code: "invalid_request" });
    const down = new HttpDataClient(fakeFetch([new Response("bad gateway", { status: 502 })]).impl);
    await expect(down.catalogue()).rejects.toMatchObject({ code: "service_unavailable" });
  });

  it("stops polling when the request is superseded", async () => {
    const controller = new AbortController();
    const { impl } = fakeFetch([json({ finished: false, state: "accepted", links: { self: "/r/1" } })]);
    const pending = new HttpDataClient(impl, 10_000).pointField(intent, controller.signal);
    controller.abort();
    await expect(pending).rejects.toBeDefined();
  });
});

describe("HttpDataClient observations", () => {
  it("reads both halves of the catalogue, keeping an unreadable observation half as null", async () => {
    const ok = new HttpDataClient(fakeFetch([json({ versions: [], observation_versions: [{ dataset_version_id: "o1" }] })]).impl);
    expect((await ok.catalogue()).observations).toEqual([{ dataset_version_id: "o1" }]);
    const down = new HttpDataClient(fakeFetch([json({
      versions: [], observation_versions: null,
      observation_failure: { code: "observation_catalogue_unavailable", message: "m" },
    })]).impl);
    expect((await down.catalogue()).observations).toBeNull();
  });

  it("asks for markers and an exact profile by query string", async () => {
    const markers = fakeFetch([json({ wire_format: "w" })]);
    await new HttpDataClient(markers.impl).observationMarkers({
      dataset_version_id: "o1", west: 60, east: 90, south: 0, north: 25,
      time_start: "2024-09-01T00:00:00Z", time_end: "2024-09-10T00:00:00Z",
    });
    expect(markers.calls[0]).toBe("/api/v1/observation-markers?dataset_version_id=o1&west=60&east=90&south=0&north=25&time_start=2024-09-01T00%3A00%3A00Z&time_end=2024-09-10T00%3A00%3A00Z");

    const profile = fakeFetch([json({ wire_format: "w" })]);
    await new HttpDataClient(profile.impl).observationProfile({
      dataset_version_id: "o1", platform_id: "5907085", cycle: "32", variables: ["TEMP", "PSAL"],
    });
    expect(profile.calls[0]).toBe("/api/v1/observation-profiles?dataset_version_id=o1&platform_id=5907085&cycle=32&variables=TEMP&variables=PSAL");
  });
});
