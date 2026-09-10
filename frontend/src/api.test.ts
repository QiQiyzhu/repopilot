import { afterEach, describe, expect, it, vi } from "vitest";
import { api, percent, seconds, terminal } from "./api";
afterEach(() => vi.unstubAllGlobals());
describe("API boundary", () => {
  it("GET requests omit bodies and report unknown metrics honestly", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) });
    vi.stubGlobal("fetch", fetch);
    await api("/health");
    expect(fetch).toHaveBeenCalledWith("/api/health", { method: "GET" });
    expect(percent(null)).toBe("—");
    expect(seconds(undefined)).toBe("—");
    expect(percent(0)).toBe("0.0%");
  });
  it("POST requests serialize the exact action", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetch);
    await api("/tasks/id/approval", "POST", { approved: false });
    expect(fetch.mock.calls[0][1].body).toBe('{"approved":false}');
  });
  it("an API failure is never returned as a successful task", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({
          ok: false,
          status: 422,
          json: async () => ({ detail: "Repository denied" }),
        }),
    );
    await expect(api("/tasks", "POST", {})).rejects.toThrow(
      "Repository denied",
    );
  });
  it("approval is still active and an unverified finish is terminal", () => {
    expect(terminal("awaiting_approval")).toBe(false);
    expect(terminal("unverified")).toBe(true);
    expect(terminal("timed_out")).toBe(true);
  });
});
