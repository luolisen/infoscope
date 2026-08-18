import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/ask", () => ({
  askHistoryQueryKey: ["ask", "history"],
  askQueryKey: (askId: string) => ["ask", askId],
  createAsk: vi.fn(),
  fetchAsk: vi.fn(),
  fetchAskHistory: vi.fn(),
}));
vi.mock("../../api/events", () => ({ eventDetailQueryKey: (eventId: string) => ["events", eventId] }));
vi.mock("../../api/now", () => ({ nowQueryKey: ["now"] }));

import { createAsk, fetchAsk, fetchAskHistory } from "../../api/ask";
import { AskPanel } from "./AskPanel";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AskPanel", () => {
  it("passes the explicit Grok toggle with the immutable Ask submission", async () => {
    vi.mocked(createAsk).mockResolvedValue({ ask_id: "ask-grok", status: "pending" });
    vi.mocked(fetchAsk).mockImplementation(() => new Promise(() => undefined));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><AskPanel onClearSelection={() => undefined} selectedEvents={[{ id: "event-1", title: "Event" }]} /></QueryClientProvider>);

    fireEvent.change(screen.getByLabelText("Grok 增强搜索"), { target: { value: "on" } });
    fireEvent.change(screen.getByLabelText("你的问题"), { target: { value: "What changed?" } });
    fireEvent.click(screen.getByRole("button", { name: "发送问题" }));

    await waitFor(() => expect(createAsk).toHaveBeenCalledWith(["event-1"], "What changed?", true));
  });

  it("does not show progress before submission and locks the submitted Ask while polling", async () => {
    vi.mocked(createAsk).mockResolvedValue({ ask_id: "ask-1", status: "pending" });
    vi.mocked(fetchAsk).mockResolvedValue({ ask_id: "ask-1", status: "pending", progress: { stage: "comparing", elapsed_seconds: 4 }, result: null, error: null });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(<QueryClientProvider client={queryClient}><AskPanel onClearSelection={() => undefined} selectedEvents={[{ id: "event-1", title: "Frozen event title" }]} /></QueryClientProvider>);

    expect(screen.queryByText(/正在比较 Event 数据库/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("你的问题"), { target: { value: "What changed?" } });
    fireEvent.click(screen.getByRole("button", { name: "发送问题" }));

    expect(await screen.findByText(/正在比较 Event 数据库/)).toBeInTheDocument();
    expect(screen.getByText("4 秒")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "处理中" })).toBeDisabled();
    expect(screen.getByText(/Frozen event title/)).toBeInTheDocument();
  });

  it("keeps the Ask locked when polling has a transport error", async () => {
    vi.mocked(createAsk).mockResolvedValue({ ask_id: "ask-1", status: "pending" });
    vi.mocked(fetchAsk).mockRejectedValue(new Error("network unavailable"));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(<QueryClientProvider client={queryClient}><AskPanel onClearSelection={() => undefined} selectedEvents={[{ id: "event-1", title: "Selected event" }]} /></QueryClientProvider>);
    fireEvent.change(screen.getByLabelText("你的问题"), { target: { value: "What changed?" } });
    fireEvent.click(screen.getByRole("button", { name: "发送问题" }));

    expect(await screen.findByText(/无法检查该 Ask/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "处理中" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重试状态检查" })).toBeInTheDocument();
  });

  it("polls the accepted Ask and refreshes NOW and updated event details on completion", async () => {
    vi.mocked(createAsk).mockResolvedValue({ ask_id: "ask-1", status: "pending" });
    vi.mocked(fetchAsk).mockResolvedValue({
      ask_id: "ask-1",
      status: "completed",
      progress: { stage: "finalizing", elapsed_seconds: 18 },
      error: null,
      result: { answer: "Current answer", event_ids: ["event-1"], claim_ids: [], timeline_ids: [], conflict_ids: [], evidence_ids: [], updated_event_ids: ["event-1"] },
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    render(<QueryClientProvider client={queryClient}><AskPanel onClearSelection={() => undefined} selectedEvents={[{ id: "event-1", title: "Selected event" }]} /></QueryClientProvider>);
    fireEvent.change(screen.getByLabelText("你的问题"), { target: { value: "What changed?" } });
    fireEvent.click(screen.getByRole("button", { name: "发送问题" }));

    expect(await screen.findByText("Current answer")).toBeInTheDocument();
    expect(screen.getByText("已思考 18 秒")).toBeInTheDocument();
    expect(screen.getByText("分析回答，不作为 Evidence。")).toBeInTheDocument();
    expect(screen.getByText(/Selected event/)).toBeInTheDocument();
    expect(screen.getByText(/事件信息已补充/)).toBeInTheDocument();
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["now"] }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["events", "event-1"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["ask", "history"] });
  });

  it("keeps the terminal exchange while the composer accepts another Ask", async () => {
    vi.mocked(createAsk).mockResolvedValue({ ask_id: "ask-1", status: "pending" });
    vi.mocked(fetchAsk).mockResolvedValue({
      ask_id: "ask-1", status: "completed", progress: { stage: "finalizing", elapsed_seconds: 9 }, error: null,
      result: { answer: "Current answer", event_ids: ["event-1"], claim_ids: [], timeline_ids: [], conflict_ids: [], evidence_ids: [], updated_event_ids: [] },
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(<QueryClientProvider client={queryClient}><AskPanel onClearSelection={() => undefined} selectedEvents={[{ id: "event-1", title: "Original event" }]} /></QueryClientProvider>);
    fireEvent.change(screen.getByLabelText("你的问题"), { target: { value: "What changed?" } });
    fireEvent.click(screen.getByRole("button", { name: "发送问题" }));
    expect(await screen.findByText("Current answer")).toBeInTheDocument();

    view.rerender(<QueryClientProvider client={queryClient}><AskPanel onClearSelection={() => undefined} selectedEvents={[{ id: "event-2", title: "Next event" }]} /></QueryClientProvider>);
    expect(screen.getByText("Current answer")).toBeInTheDocument();
    expect(screen.getByText(/Next event/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("你的问题"), { target: { value: "A follow-up" } });
    fireEvent.click(screen.getByRole("button", { name: "发送问题" }));
    await waitFor(() => expect(createAsk).toHaveBeenLastCalledWith(["event-2"], "A follow-up", false));
  });

  it("automatically loads history for the selected Event as a conversation", async () => {
    vi.mocked(fetchAskHistory).mockResolvedValue({
      items: [{ ask_id: "history-1", status: "completed", question: "历史问题", event_ids: ["event-1"], created_at: "2026-08-18T00:00:00Z", finished_at: "2026-08-18T00:00:12Z", thinking_seconds: 12, answer: "历史回答", updated_event_ids: [] }],
      next_cursor: null,
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(<QueryClientProvider client={queryClient}><AskPanel onClearSelection={() => undefined} selectedEvents={[{ id: "event-1", title: "Event" }]} workspace /></QueryClientProvider>);

    expect(await screen.findByText("历史问题")).toBeInTheDocument();
    expect(screen.getByText("历史回答")).toBeInTheDocument();
    expect(screen.getByText("已思考 12 秒")).toBeInTheDocument();
    expect(fetchAskHistory).toHaveBeenCalledWith(100);
  });
});
