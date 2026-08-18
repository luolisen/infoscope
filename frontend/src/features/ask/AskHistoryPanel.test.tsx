import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("../../api/ask", () => ({
  askHistoryQueryKey: ["ask", "history"],
  fetchAskHistory: vi.fn(),
}));

import { fetchAskHistory } from "../../api/ask";
import { AskHistoryPanel } from "./AskHistoryPanel";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.resetAllMocks();
});

it("uses the Backend opaque cursor to load more owner history", async () => {
  vi.mocked(fetchAskHistory)
    .mockResolvedValueOnce({
      items: [{ ask_id: "ask-1", status: "completed", question: "第一问", event_ids: [], created_at: "2026-08-18T00:00:00Z", finished_at: null, answer: "回答一", updated_event_ids: [] }],
      next_cursor: "opaque-next",
    })
    .mockResolvedValueOnce({
      items: [{ ask_id: "ask-2", status: "failed", question: "第二问", event_ids: [], created_at: "2026-08-17T00:00:00Z", finished_at: null, answer: null, updated_event_ids: [] }],
      next_cursor: null,
    });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><AskHistoryPanel /></QueryClientProvider>);

  fireEvent.click(screen.getByRole("button", { name: "展开 Ask 历史" }));
  expect(await screen.findByText("第一问")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "加载更多" }));
  expect(await screen.findByText("第二问")).toBeInTheDocument();
  expect(fetchAskHistory).toHaveBeenLastCalledWith(20, "opaque-next");
});

it("uses explicit controls for expansion and persisted pinning", async () => {
  vi.mocked(fetchAskHistory).mockResolvedValue({ items: [], next_cursor: null });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><AskHistoryPanel /></QueryClientProvider>);

  const panel = screen.getByRole("complementary", { name: "Ask 历史" });
  fireEvent.mouseEnter(panel);
  fireEvent.click(screen.getByRole("button", { name: "展开 Ask 历史" }));
  fireEvent.mouseLeave(panel);
  expect(screen.getByRole("button", { name: "折叠 Ask 历史" })).toHaveAttribute("aria-expanded", "true");

  const pin = screen.getByRole("button", { name: "固定 Ask 历史" });
  fireEvent.click(pin);
  expect(screen.getByRole("button", { name: "取消固定 Ask 历史" })).toHaveAttribute("aria-pressed", "true");
  expect(window.localStorage.getItem("infoscope.ask-history.pinned")).toBe("true");
});
