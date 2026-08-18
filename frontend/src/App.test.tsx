import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
vi.mock("./api/ask", () => ({
  askHistoryQueryKey: ["ask", "history"],
  askQueryKey: (askId: string) => ["ask", askId],
  createAsk: vi.fn(),
  fetchAsk: vi.fn(),
  fetchAskHistory: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
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

    expect(await screen.findByRole("heading", { name: "建立你的视野。" })).toBeInTheDocument();
    expect(screen.getByLabelText("用户名")).toBeInTheDocument();
    expect(screen.getByLabelText("密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交登录" })).toBeInTheDocument();
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

    expect(await screen.findByRole("heading", { name: "此刻，什么值得关注。" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "NOW" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByText(/暂时没有需要关注的内容/)).toBeInTheDocument();
  });

  it("returns focus to the search trigger after Escape closes the overlay", async () => {
    vi.mocked(fetchSession).mockResolvedValue({ state: "ready", user: { username: "lingjiu" } });
    vi.mocked(fetchHealth).mockResolvedValue({ status: "ok", api: "ok", database: "ok", worker: "ok" });
    vi.mocked(fetchNow).mockResolvedValue({ items: [], next_cursor: null, window_stats: { raw_information_count: 0, event_count: 0, relevant_event_count: 0, window_started_at: "2026-01-01T00:00:00Z", window_ended_at: "2026-01-01T01:00:00Z" } });

    renderApp();
    const trigger = await screen.findByRole("button", { name: "搜索，快捷键 Command K" });
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "搜索 Event" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(document.activeElement).toBe(trigger));
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
    expect(screen.getByText("更改将在下次Event更新时生效")).toBeInTheDocument();
  });

  it("renders the Ask Event picker inside the sidebar below navigation", async () => {
    window.location.hash = "#ask";
    vi.mocked(fetchSession).mockResolvedValue({ state: "ready", user: { username: "lingjiu" } });
    vi.mocked(fetchHealth).mockResolvedValue({ status: "ok", api: "ok", database: "ok", worker: "ok" });
    vi.mocked(fetchNow).mockResolvedValue({
      items: [{ id: "event-1", title: "可选择的 Event", overview: "Overview", state: "developing", display_time: "2026-01-01T00:30:00Z", updated_at: "2026-01-01T00:30:00Z", why_it_matters: "Why", new_claim_count: 0, conflict_count: 0, topics: [], saved: false }],
      next_cursor: null,
      window_stats: { raw_information_count: 1, event_count: 1, relevant_event_count: 1, window_started_at: "2026-01-01T00:00:00Z", window_ended_at: "2026-01-01T01:00:00Z" },
    });

    renderApp();

    expect(await screen.findByRole("heading", { name: "观澜能帮忙做什么" })).toBeInTheDocument();
    const sidebar = screen.getByRole("complementary", { name: "Primary navigation" });
    expect(sidebar).toContainElement(screen.getByRole("heading", { name: "Event 列表" }));
    expect(sidebar).toContainElement(await screen.findByRole("checkbox", { name: "选择 可选择的 Event" }));
  });
});
