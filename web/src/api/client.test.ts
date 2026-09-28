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
