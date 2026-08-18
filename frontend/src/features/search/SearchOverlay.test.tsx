import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/archiveSearch", () => ({ searchEvents: vi.fn(), searchQueryKey: (query: string) => ["search", "events", query] }));
vi.mock("../events/SaveButton", () => ({ SaveButton: () => null }));

import { searchEvents } from "../../api/archiveSearch";
import { SearchOverlay } from "./SearchOverlay";

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("SearchOverlay", () => {
  it("does not search or show loading before a query is submitted", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><SearchOverlay onClose={() => undefined} open /></QueryClientProvider>);

    expect(screen.queryByText("搜索中…")).not.toBeInTheDocument();
    expect(searchEvents).not.toHaveBeenCalled();
  });

  it("traps Tab focus inside the dialog", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><SearchOverlay onClose={() => undefined} open /></QueryClientProvider>);

    const close = screen.getByRole("button", { name: "关闭搜索" });
    const submit = screen.getByRole("button", { name: "搜索" });
    submit.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(submit);
  });

  it("submits normalized text to the generated Search endpoint and links results", async () => {
    vi.mocked(searchEvents).mockResolvedValue({ next_cursor: null, items: [{ id: "event-1", title: "Matching event", overview: "Overview", state: "developing", display_time: "2026-08-16T13:00:00Z", updated_at: "2026-08-16T13:00:00Z", why_it_matters: "Why", new_claim_count: 0, conflict_count: 0, topics: [], saved: false }] });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><SearchOverlay onClose={() => undefined} open /></QueryClientProvider>);

    fireEvent.change(screen.getByPlaceholderText("搜索历史 Event"), { target: { value: "  AI\n model " } });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));

    expect(await screen.findByRole("link", { name: "Matching event" })).toHaveAttribute("href", "#event/event-1");
    expect(searchEvents).toHaveBeenCalledWith("AI model", null);
  });

  it("uses the backend opaque cursor when loading the next page", async () => {
    vi.mocked(searchEvents)
      .mockResolvedValueOnce({ next_cursor: "opaque-cursor", items: [{ id: "event-1", title: "First", overview: "Overview", state: "developing", display_time: "2026-08-16T13:00:00Z", updated_at: "2026-08-16T13:00:00Z", why_it_matters: "Why", new_claim_count: 0, conflict_count: 0, topics: [], saved: false }] })
      .mockResolvedValueOnce({ next_cursor: null, items: [{ id: "event-2", title: "Second", overview: "Overview", state: "developing", display_time: "2026-08-16T12:00:00Z", updated_at: "2026-08-16T12:00:00Z", why_it_matters: "Why", new_claim_count: 0, conflict_count: 0, topics: [], saved: false }] });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><SearchOverlay onClose={() => undefined} open /></QueryClientProvider>);

    fireEvent.change(screen.getByPlaceholderText("搜索历史 Event"), { target: { value: "AI" } });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    await screen.findByRole("link", { name: "First" });
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }));

    await screen.findByRole("link", { name: "Second" });
    expect(searchEvents).toHaveBeenLastCalledWith("AI", "opaque-cursor");
  });

  it("keeps the first page visible when loading the next page fails", async () => {
    vi.mocked(searchEvents)
      .mockResolvedValueOnce({ next_cursor: "opaque-cursor", items: [{ id: "event-1", title: "First page result", overview: "Overview", state: "developing", display_time: "2026-08-16T13:00:00Z", updated_at: "2026-08-16T13:00:00Z", why_it_matters: "Why", new_claim_count: 0, conflict_count: 0, topics: [], saved: false }] })
      .mockRejectedValueOnce(new Error("next page failed"));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><SearchOverlay onClose={() => undefined} open /></QueryClientProvider>);

    fireEvent.change(screen.getByPlaceholderText("搜索历史 Event"), { target: { value: "AI" } });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    await screen.findByRole("link", { name: "First page result" });
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }));

    expect(await screen.findByText("无法加载更多结果。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "First page result" })).toBeInTheDocument();
    expect(screen.queryByText("暂时无法搜索历史 Event。")).not.toBeInTheDocument();
  });
});
