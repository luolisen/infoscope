import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/ask", () => ({
  askHistoryQueryKey: ["ask", "history"],
  askQueryKey: (askId: string) => ["ask", askId],
  createAsk: vi.fn(),
  fetchAsk: vi.fn(),
}));
vi.mock("../../api/events", () => ({ eventDetailQueryKey: (eventId: string) => ["events", eventId] }));
vi.mock("../../api/now", () => ({ nowQueryKey: ["now"] }));

import { createAsk, fetchAsk } from "../../api/ask";
import { AskPanel } from "./AskPanel";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AskPanel", () => {
  it("does not show progress before submission and locks the submitted Ask while polling", async () => {
    vi.mocked(createAsk).mockResolvedValue({ ask_id: "ask-1", status: "pending" });
    vi.mocked(fetchAsk).mockImplementation(() => new Promise(() => undefined));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(<QueryClientProvider client={queryClient}><AskPanel onClearSelection={() => undefined} selectedEvents={[{ id: "event-1", title: "Frozen event title" }]} /></QueryClientProvider>);

    expect(screen.queryByText(/正在整理相关信息/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("你的问题"), { target: { value: "What changed?" } });
    fireEvent.click(screen.getByRole("button", { name: "发送问题" }));

    expect(await screen.findByText(/正在整理相关信息/)).toBeInTheDocument();
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
      error: null,
      result: { answer: "Current answer", event_ids: ["event-1"], claim_ids: [], timeline_ids: [], conflict_ids: [], evidence_ids: [], updated_event_ids: ["event-1"] },
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    render(<QueryClientProvider client={queryClient}><AskPanel onClearSelection={() => undefined} selectedEvents={[{ id: "event-1", title: "Selected event" }]} /></QueryClientProvider>);
    fireEvent.change(screen.getByLabelText("你的问题"), { target: { value: "What changed?" } });
    fireEvent.click(screen.getByRole("button", { name: "发送问题" }));

    expect(await screen.findByText("Current answer")).toBeInTheDocument();
    expect(screen.getByText("分析回答，不作为 Evidence。")).toBeInTheDocument();
    expect(screen.getByText(/Selected event/)).toBeInTheDocument();
    expect(screen.getByText(/事件信息已补充/)).toBeInTheDocument();
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["now"] }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["events", "event-1"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["ask", "history"] });
  });

  it("clears the terminal snapshot only through an explicit new Ask transition", async () => {
    vi.mocked(createAsk).mockResolvedValue({ ask_id: "ask-1", status: "pending" });
    vi.mocked(fetchAsk).mockResolvedValue({
      ask_id: "ask-1", status: "completed", error: null,
      result: { answer: "Current answer", event_ids: ["event-1"], claim_ids: [], timeline_ids: [], conflict_ids: [], evidence_ids: [], updated_event_ids: [] },
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(<QueryClientProvider client={queryClient}><AskPanel onClearSelection={() => undefined} selectedEvents={[{ id: "event-1", title: "Original event" }]} /></QueryClientProvider>);
    fireEvent.change(screen.getByLabelText("你的问题"), { target: { value: "What changed?" } });
    fireEvent.click(screen.getByRole("button", { name: "发送问题" }));
    expect(await screen.findByText("Current answer")).toBeInTheDocument();

    view.rerender(<QueryClientProvider client={queryClient}><AskPanel onClearSelection={() => undefined} selectedEvents={[{ id: "event-2", title: "Next event" }]} /></QueryClientProvider>);
    expect(screen.getByText(/Original event/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "再问一个问题" }));

    expect(screen.getByText(/Next event/)).toBeInTheDocument();
    expect(screen.queryByText("Current answer")).not.toBeInTheDocument();
  });
});
