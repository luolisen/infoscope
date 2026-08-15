import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./api/health", () => ({ fetchHealth: vi.fn() }));
vi.mock("./api/session", () => ({
  fetchSession: vi.fn(),
  sessionQueryKey: ["session"],
}));
vi.mock("./api/now", () => ({ fetchNow: vi.fn(), nowQueryKey: ["now"] }));

import { App } from "./App";
import { fetchHealth } from "./api/health";
import { fetchSession } from "./api/session";
import { fetchNow } from "./api/now";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);
}

describe("App", () => {
  it("shows the credential-only access screen for anonymous sessions", async () => {
    vi.mocked(fetchSession).mockResolvedValue({ state: "anonymous", user: null });

    renderApp();

    expect(await screen.findByRole("heading", { name: /establish your view/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit log in" })).toBeInTheDocument();
  });

  it("shows the editorial app shell and health success state", async () => {
    vi.mocked(fetchSession).mockResolvedValue({
      state: "ready", user: { username: "lingjiu" },
    });
    vi.mocked(fetchHealth).mockResolvedValue({
      status: "ok", api: "ok", database: "ok", worker: "ok",
    });
    vi.mocked(fetchNow).mockResolvedValue({ items: [], next_cursor: null, window_stats: { raw_information_count: 0, event_count: 0, relevant_event_count: 0, window_started_at: "2026-01-01T00:00:00Z", window_ended_at: "2026-01-01T01:00:00Z" } });

    renderApp();

    expect(await screen.findByRole("heading", { name: /what matters now/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "NOW" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByText(/nothing requires your attention/i)).toBeInTheDocument();
  });
});
