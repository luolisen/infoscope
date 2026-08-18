import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
import { fetchOnboarding, updateOnboarding } from "./api/onboarding";

beforeEach(() => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  window.location.hash = "";
});

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);
}

describe("App", () => {
  it("only asks how to address an anonymous local user", async () => {
    vi.mocked(fetchSession).mockResolvedValue({ state: "anonymous", user: null });

    renderApp();

    expect(await screen.findByRole("heading", { name: "我们怎么称呼您？" })).toBeInTheDocument();
    expect(screen.getByLabelText("称呼")).toBeInTheDocument();
    expect(screen.queryByLabelText("用户名")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("密码")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "继续建立视野" })).toBeInTheDocument();
  });

  it("shows the editorial app shell and health success state", async () => {
    vi.mocked(fetchSession).mockResolvedValue({
      state: "ready", user: { display_name: "Lingjiu" },
    });
    vi.mocked(fetchHealth).mockResolvedValue({
      status: "ok", api: "ok", database: "ok", worker: "ok",
    });
    vi.mocked(fetchNow).mockResolvedValue({ corpus_stats: { raw_information_count: 0, signal_count: 0 }, items: [], next_cursor: null, window_stats: { raw_information_count: 0, signal_count: 0, event_count: 0, relevant_event_count: 0, window_started_at: "2026-01-01T00:00:00Z", window_ended_at: "2026-01-01T01:00:00Z" } });

    renderApp();

    expect(await screen.findByRole("heading", { name: "此刻，什么值得关注。" })).toBeInTheDocument();
    expect(screen.queryByText(/SYSTEM \/ (ONLINE|CHECKING)/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "NOW" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("当前已有 Raw 0 条 · 因子 0 个 · 当前 Event 0 个"))
      .toBeInTheDocument();
    expect(await screen.findByText(/暂时没有需要关注的内容/)).toBeInTheDocument();
  });

  it("filters NOW Events by Backend state without changing their order", async () => {
    vi.mocked(fetchSession).mockResolvedValue({ state: "ready", user: { display_name: "Lingjiu" } });
    vi.mocked(fetchHealth).mockResolvedValue({ status: "ok", api: "ok", database: "ok", worker: "ok" });
    vi.mocked(fetchNow).mockResolvedValue({
      items: [
        { id: "event-developing", title: "发展中的 Event", overview: "Overview", state: "developing", display_time: "2026-01-01T00:30:00Z", updated_at: "2026-01-01T00:30:00Z", why_it_matters: "Why", new_claim_count: 0, conflict_count: 0, topics: [], saved: false },
        { id: "event-conflicting", title: "存在冲突的 Event", overview: "Overview", state: "conflicting", display_time: "2026-01-01T00:20:00Z", updated_at: "2026-01-01T00:20:00Z", why_it_matters: "Why", new_claim_count: 0, conflict_count: 1, topics: [], saved: false },
      ],
      next_cursor: null,
      corpus_stats: { raw_information_count: 20, signal_count: 18 },
      window_stats: { raw_information_count: 2, signal_count: 2, event_count: 2, relevant_event_count: 2, window_started_at: "2026-01-01T00:00:00Z", window_ended_at: "2026-01-01T01:00:00Z" },
    });

    renderApp();
    expect(await screen.findByRole("link", { name: "发展中的 Event" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "存在冲突的 Event" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "存在冲突" }));
    expect(screen.queryByRole("link", { name: "发展中的 Event" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "存在冲突的 Event" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "存在冲突" })).toHaveAttribute("aria-pressed", "true");
  });

  it("returns focus to the search trigger after Escape closes the overlay", async () => {
    vi.mocked(fetchSession).mockResolvedValue({ state: "ready", user: { display_name: "Lingjiu" } });
    vi.mocked(fetchHealth).mockResolvedValue({ status: "ok", api: "ok", database: "ok", worker: "ok" });
    vi.mocked(fetchNow).mockResolvedValue({ corpus_stats: { raw_information_count: 0, signal_count: 0 }, items: [], next_cursor: null, window_stats: { raw_information_count: 0, signal_count: 0, event_count: 0, relevant_event_count: 0, window_started_at: "2026-01-01T00:00:00Z", window_ended_at: "2026-01-01T01:00:00Z" } });

    renderApp();
    const trigger = await screen.findByRole("button", { name: "搜索，快捷键 Command K" });
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "搜索 Event" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("resets the document scroll position on hash-route changes", async () => {
    vi.mocked(fetchSession).mockResolvedValue({ state: "ready", user: { display_name: "Lingjiu" } });
    vi.mocked(fetchHealth).mockResolvedValue({ status: "ok", api: "ok", database: "ok", worker: "ok" });
    vi.mocked(fetchNow).mockResolvedValue({ corpus_stats: { raw_information_count: 0, signal_count: 0 }, items: [], next_cursor: null, window_stats: { raw_information_count: 0, signal_count: 0, event_count: 0, relevant_event_count: 0, window_started_at: "2026-01-01T00:00:00Z", window_ended_at: "2026-01-01T01:00:00Z" } });

    renderApp();
    await screen.findByRole("heading", { name: "此刻，什么值得关注。" });
    vi.mocked(window.scrollTo).mockClear();
    window.location.hash = "#ask";
    window.dispatchEvent(new HashChangeEvent("hashchange"));

    await waitFor(() => expect(window.scrollTo).toHaveBeenCalledWith({ behavior: "auto", left: 0, top: 0 }));
  });

  it("marks only Settings as the current navigation page on the maintenance route", async () => {
    window.location.hash = "#settings";
    vi.mocked(fetchSession).mockResolvedValue({ state: "ready", user: { display_name: "Lingjiu" } });
    vi.mocked(fetchHealth).mockResolvedValue({ status: "ok", api: "ok", database: "ok", worker: "ok" });
    vi.mocked(fetchMaintenanceStatus).mockResolvedValue({ status: "idle", phase: null, cycle_started_at: null, cycle_finished_at: null, next_cycle_at: null });

    renderApp();

    expect(await screen.findByRole("heading", { name: /保持事实层最新/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "SETTINGS" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "NOW" })).not.toHaveAttribute("aria-current");
  });

  it("replays onboarding from Settings without persisting demo choices", async () => {
    window.location.hash = "#settings";
    vi.mocked(fetchSession).mockResolvedValue({ state: "ready", user: { display_name: "Alan" } });
    vi.mocked(fetchHealth).mockResolvedValue({ status: "ok", api: "ok", database: "ok", worker: "ok" });
    vi.mocked(fetchMaintenanceStatus).mockResolvedValue({ status: "idle", phase: null, cycle_started_at: null, cycle_finished_at: null, next_cycle_at: null });
    vi.mocked(fetchNow).mockResolvedValue({ corpus_stats: { raw_information_count: 0, signal_count: 0 }, items: [], next_cursor: null, window_stats: { raw_information_count: 0, signal_count: 0, event_count: 0, relevant_event_count: 0, window_started_at: "2026-01-01T00:00:00Z", window_ended_at: "2026-01-01T01:00:00Z" } });
    vi.mocked(fetchOnboarding).mockResolvedValue({
      completed: true,
      scope_options: [{ id: "ai", label: "AI" }, { id: "science", label: "科学" }],
      investment_market_options: [],
      focus_options: [{ id: "major_changes", label: "重要变化" }, { id: "deep_context", label: "深度背景" }],
      answers: { scope_ids: ["ai"], investment_market_ids: [], focus_ids: ["major_changes"] },
    });

    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "演示demo" }));
    expect(screen.getByRole("heading", { name: "我们怎么称呼您？" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("称呼"), { target: { value: "临时演示称呼" } });
    fireEvent.click(screen.getByRole("button", { name: "继续建立视野" }));

    expect(await screen.findByRole("heading", { name: "哪些内容进入你的视野？" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /AI/ })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: /科学/ }));
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    expect(await screen.findByRole("heading", { name: "什么内容应该更容易浮上来？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /深度背景/ }));
    fireEvent.click(screen.getByRole("button", { name: "进入演示" }));

    expect(updateOnboarding).not.toHaveBeenCalled();
    expect(await screen.findByRole("heading", { name: "此刻，什么值得关注。" })).toBeInTheDocument();
  });

  it("marks Brief as the only current primary navigation page on the Brief route", async () => {
    window.location.hash = "#brief";
    vi.mocked(fetchSession).mockResolvedValue({ state: "ready", user: { display_name: "Lingjiu" } });
    vi.mocked(fetchHealth).mockResolvedValue({ status: "ok", api: "ok", database: "ok", worker: "ok" });
    vi.mocked(fetchLatestBrief).mockResolvedValue({ generated_at: null, items: [] });

    renderApp();

    expect(await screen.findByRole("heading", { name: /Brief 正在等待/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "BRIEF" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "NOW" })).not.toHaveAttribute("aria-current");
  });

  it("renders the saved onboarding choices on the Scope route", async () => {
    window.location.hash = "#scope";
    vi.mocked(fetchSession).mockResolvedValue({ state: "ready", user: { display_name: "Lingjiu" } });
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
    vi.mocked(fetchSession).mockResolvedValue({ state: "ready", user: { display_name: "Lingjiu" } });
    vi.mocked(fetchHealth).mockResolvedValue({ status: "ok", api: "ok", database: "ok", worker: "ok" });
    vi.mocked(fetchNow).mockResolvedValue({
      items: [{ id: "event-1", title: "可选择的 Event", overview: "Overview", state: "developing", display_time: "2026-01-01T00:30:00Z", updated_at: "2026-01-01T00:30:00Z", why_it_matters: "Why", new_claim_count: 0, conflict_count: 0, topics: [], saved: false }],
      next_cursor: null,
      corpus_stats: { raw_information_count: 10, signal_count: 9 },
      window_stats: { raw_information_count: 1, signal_count: 1, event_count: 1, relevant_event_count: 1, window_started_at: "2026-01-01T00:00:00Z", window_ended_at: "2026-01-01T01:00:00Z" },
    });

    renderApp();

    expect(await screen.findByRole("heading", { name: "观澜能帮忙做什么" })).toBeInTheDocument();
    const sidebar = screen.getByRole("complementary", { name: "Primary navigation" });
    expect(sidebar).toContainElement(screen.getByRole("heading", { name: "Event 列表" }));
    const checkbox = await screen.findByRole("checkbox", { name: "选择 可选择的 Event" });
    expect(sidebar).toContainElement(checkbox);
    expect(sidebar).toHaveTextContent("0 / 8");
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
    expect(checkbox.closest("label")).toHaveClass("ask-event-option--selected");
    expect(checkbox.closest("label")).toHaveTextContent("01");
    expect(sidebar).toHaveTextContent("1 / 8");
  });
});
