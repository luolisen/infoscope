import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/ask", () => ({
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

    render(<QueryClientProvider client={queryClient}><AskPanel onClearSelection={() => undefined} selectedEventIds={["event-1"]} /></QueryClientProvider>);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "What changed?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask Infoscope" }));

    expect(await screen.findByText("Current answer")).toBeInTheDocument();
    expect(screen.getByText(/事件信息已补充/)).toBeInTheDocument();
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["now"] }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["events", "event-1"] });
  });
});
