import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/events", () => ({
  eventDetailQueryKey: (eventId: string) => ["events", eventId],
  fetchEventDetail: vi.fn(),
}));

import { fetchEventDetail } from "../../api/events";
import { EventDetail } from "./EventDetail";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderDetail() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><EventDetail eventId="event-1" onBack={() => undefined} onToggleEventSelection={() => undefined} selectedEvents={[]} /></QueryClientProvider>);
}

describe("EventDetail", () => {
  it("renders API ordering and never invents private source attribution", async () => {
    vi.mocked(fetchEventDetail).mockResolvedValue({
      id: "event-1",
      title: "Event title",
      overview: "Current overview",
      state: "developing",
      display_time: "2026-08-16T00:00:00Z",
      updated_at: "2026-08-16T01:00:00Z",
      base_analysis: { summary: "Analysis", event_type: "technology", importance: "medium", topics: ["AI"], entities: [] },
      why_it_matters: "Context",
      topics: ["AI"],
      saved: false,
      claims: [{ id: "claim-1", text: "First claim", state: "unresolved", evidence_ids: ["evidence-private", "evidence-public"] }],
      timeline: [{ id: "timeline-1", occurred_at: "2026-08-15T00:00:00Z", summary: "First timeline entry", claim_ids: ["claim-1"] }],
      conflicts: [{ id: "conflict-1", summary: "The claim is disputed", claim_ids: ["claim-1"], evidence_ids: ["evidence-public"] }],
      evidence: [
        { id: "evidence-private", platform: "telegram", visibility: "private_sanitized", author_name: null, url: null, published_at: null, excerpt: "Sanitized private text" },
        { id: "evidence-public", platform: "web", visibility: "public", author_name: "Public desk", url: "https://example.test/source", published_at: "2026-08-15T01:00:00Z", excerpt: "Public supporting text" },
      ],
    });

    renderDetail();

    expect(await screen.findByRole("heading", { name: "Event title" })).toBeInTheDocument();
    expect(screen.getByText("First timeline entry")).toBeInTheDocument();
    expect(screen.getAllByText("Sanitized private text")).toHaveLength(2);
    expect(screen.getAllByText("Public supporting text")).toHaveLength(3);
    expect(screen.getAllByText("First claim")).toHaveLength(2);
    expect(screen.getByRole("link", { name: /打开公开来源/ })).toHaveAttribute("href", "https://example.test/source");
    expect(screen.getByText(/Public desk/)).toBeInTheDocument();
    expect(screen.getByText("EVENT / 发展中")).toBeInTheDocument();
    expect(screen.getByText("BASE ANALYSIS / 中")).toBeInTheDocument();
    expect(screen.getByText("待确认")).toBeInTheDocument();
    expect(screen.getByText("telegram / 私密·已脱敏")).toBeInTheDocument();
    expect(screen.getByText("web / 公开")).toBeInTheDocument();
    expect(screen.queryByText(/telegram\.me|invite|username/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "加入询问选择" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "加入询问选择" })).toHaveClass("detail-select-button");
  });

  it("renders loading, error, and empty relation states", async () => {
    vi.mocked(fetchEventDetail).mockImplementation(() => new Promise(() => undefined));
    const loading = renderDetail();
    expect(screen.getByText(/正在加载当前事件记录/)).toBeInTheDocument();
    loading.unmount();

    vi.mocked(fetchEventDetail).mockRejectedValue(new Error("unavailable"));
    renderDetail();
    expect(await screen.findByRole("alert")).toHaveTextContent(/无法加载该事件/);
    cleanup();

    vi.mocked(fetchEventDetail).mockResolvedValue({
      id: "event-1", title: "Empty event", overview: "Overview", state: "developing", display_time: "2026-08-16T00:00:00Z", updated_at: "2026-08-16T01:00:00Z",
      base_analysis: { summary: "Analysis", event_type: "technology", importance: "medium", topics: [], entities: [] }, why_it_matters: "Context", topics: [], saved: false,
      claims: [], timeline: [], conflicts: [], evidence: [],
    });
    renderDetail();
    expect(await screen.findByText(/暂时没有主张记录/)).toBeInTheDocument();
    expect(screen.getByText(/暂时没有时间线记录/)).toBeInTheDocument();
    expect(screen.getByText(/暂时没有未解决的冲突/)).toBeInTheDocument();
    expect(screen.getByText(/暂时没有证据/)).toBeInTheDocument();
  });
});
