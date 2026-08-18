import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./api/health", () => ({ fetchHealth: vi.fn() }));
vi.mock("./api/session", () => ({
  fetchSession: vi.fn(),
  sessionQueryKey: ["session"],
}));
vi.mock("./api/now", () => ({ fetchNow: vi.fn(), nowQueryKey: ["now"] }));
vi.mock("./api/brief", () => ({ fetchLatestBrief: vi.fn(), briefLatestQueryKey: ["brief", "latest"] }));
vi.mock("./api/onboarding", () => ({
  fetchOnboarding: vi.fn(),
  onboardingQueryKey: ["onboarding"],
  updateOnboarding: vi.fn(),
  OnboardingError: class OnboardingError extends Error {},
}));
vi.mock("./api/maintenance", () => ({
  createMaintenanceRun: vi.fn(),
  fetchMaintenanceRun: vi.fn(),
  fetchMaintenanceStatus: vi.fn(),
  maintenanceRunQueryKey: (runId: string) => ["maintenance", "runs", runId],
  maintenanceStatusQueryKey: ["maintenance", "status"],
}));

import { App } from "./App";
import { fetchHealth } from "./api/health";
import { fetchSession } from "./api/session";
import { fetchNow } from "./api/now";
import { fetchLatestBrief } from "./api/brief";
import { fetchMaintenanceStatus } from "./api/maintenance";
import { fetchOnboarding } from "./api/onboarding";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = "";
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

  it("marks only Settings as the current navigation page on the maintenance route", async () => {
    window.location.hash = "#settings";
    vi.mocked(fetchSession).mockResolvedValue({ state: "ready", user: { username: "lingjiu" } });
    vi.mocked(fetchHealth).mockResolvedValue({ status: "ok", api: "ok", database: "ok", worker: "ok" });
    vi.mocked(fetchMaintenanceStatus).mockResolvedValue({ status: "idle", phase: null, cycle_started_at: null, cycle_finished_at: null, next_cycle_at: null });

    renderApp();

    expect(await screen.findByRole("heading", { name: /保持事实层最新/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "SETTINGS" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "NOW" })).not.toHaveAttribute("aria-current");
  });

  it("marks Brief as the only current primary navigation page on the Brief route", async () => {
    window.location.hash = "#brief";
    vi.mocked(fetchSession).mockResolvedValue({ state: "ready", user: { username: "lingjiu" } });
    vi.mocked(fetchHealth).mockResolvedValue({ status: "ok", api: "ok", database: "ok", worker: "ok" });
    vi.mocked(fetchLatestBrief).mockResolvedValue({ generated_at: null, items: [] });

    renderApp();

    expect(await screen.findByRole("heading", { name: /Brief 正在等待/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "BRIEF" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "NOW" })).not.toHaveAttribute("aria-current");
  });

  it("renders the saved onboarding choices on the Scope route", async () => {
    window.location.hash = "#scope";
    vi.mocked(fetchSession).mockResolvedValue({ state: "ready", user: { username: "lingjiu" } });
    vi.mocked(fetchHealth).mockResolvedValue({ status: "ok", api: "ok", database: "ok", worker: "ok" });
    vi.mocked(fetchOnboarding).mockResolvedValue({
      completed: true,
      scope_options: [{ id: "ai", label: "AI" }, { id: "technology", label: "Technology" }],
      investment_market_options: [],
      focus_options: [{ id: "major_changes", label: "Major changes" }],
      answers: { scope_ids: ["ai"], investment_market_ids: [], focus_ids: ["major_changes"] },
    });

    renderApp();

    expect(await screen.findByRole("heading", { name: "哪些内容进入你的视野？" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "SCOPE" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "NOW" })).not.toHaveAttribute("aria-current");
    expect(await screen.findByRole("button", { name: /AI/ })).toHaveAttribute("aria-pressed", "true");
  });
});
