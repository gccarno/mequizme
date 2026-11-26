import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CloudStatus } from "../api";
import { relativeAgo } from "../lib/format";

vi.mock("../lib/firebase", () => ({ firebaseConfigured: true, signInWithGoogle: vi.fn() }));

const { CloudSync, syncLabel } = await import("./CloudSync");

const base: CloudStatus = {
  configured: true,
  connected: true,
  email: "me@example.com",
  lastSync: null,
  lastError: null,
  pending: 0,
  syncing: false,
};

function mockFetch(routes: Record<string, unknown>) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`;
      calls.push(key);
      const body = routes[key];
      if (body === undefined) return new Response(JSON.stringify({ detail: "nope" }), { status: 404 });
      return new Response(body === null ? null : JSON.stringify(body), { status: body === null ? 204 : 200 });
    }),
  );
  return calls;
}

function mount(signIn = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <CloudSync signIn={signIn} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("syncLabel", () => {
  const now = Date.parse("2026-11-26T12:00:00Z");
  it("describes each state", () => {
    expect(syncLabel(base, now)).toBe("Not synced yet");
    expect(syncLabel({ ...base, lastSync: "2026-11-26T11:55:00Z" }, now)).toBe("Synced 5 min ago");
    expect(syncLabel({ ...base, lastSync: "2026-11-26T11:55:00Z", lastError: "x" }, now)).toBe("Sync failed");
    expect(syncLabel({ ...base, syncing: true }, now)).toBe("Syncing…");
  });
  it("relativeAgo rounds sensibly", () => {
    expect(relativeAgo("2026-11-26T11:59:50Z", now)).toBe("just now");
    expect(relativeAgo("2026-11-26T09:00:00Z", now)).toBe("3 h ago");
    expect(relativeAgo("2026-11-24T12:00:00Z", now)).toBe("2 days ago");
  });
});

describe("CloudSync", () => {
  it("renders nothing when the cloud isn't configured", async () => {
    const calls = mockFetch({ "GET /api/cloud/status": { ...base, configured: false } });
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <CloudSync />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(calls).toContain("GET /api/cloud/status"));
    expect(container.innerHTML).toBe("");
  });

  it("connects: Google sign-in, hand tokens to the backend, then sync", async () => {
    const calls = mockFetch({
      "GET /api/cloud/status": { ...base, connected: false },
      "POST /api/cloud/session": { ...base },
      "POST /api/cloud/sync": { pushed: {}, pulled: {}, status: { ...base, lastSync: new Date().toISOString() } },
    });
    const signIn = vi.fn(async () => ({ idToken: "id", refreshToken: "rt" }));
    mount(signIn);
    fireEvent.click(await screen.findByRole("button", { name: "Connect phone" }));
    await screen.findByText(/Synced just now/);
    expect(signIn).toHaveBeenCalledOnce();
    expect(calls).toEqual(expect.arrayContaining(["POST /api/cloud/session", "POST /api/cloud/sync"]));
  });

  it("shows pending uploads and sync errors", async () => {
    mockFetch({ "GET /api/cloud/status": { ...base, lastSync: new Date().toISOString(), pending: 3 } });
    mount();
    await screen.findByText(/3 to upload/);
    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    await screen.findByText("Sync failed");
  });
});
