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

    expect(screen.queryByText("Searching…")).not.toBeInTheDocument();
    expect(searchEvents).not.toHaveBeenCalled();
  });

  it("submits normalized text to the generated Search endpoint and links results", async () => {
    vi.mocked(searchEvents).mockResolvedValue({ next_cursor: null, items: [{ id: "event-1", title: "Matching event", overview: "Overview", state: "developing", display_time: "2026-08-16T13:00:00Z", updated_at: "2026-08-16T13:00:00Z", why_it_matters: "Why", new_claim_count: 0, conflict_count: 0, topics: [], saved: false }] });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><SearchOverlay onClose={() => undefined} open /></QueryClientProvider>);

    fireEvent.change(screen.getByPlaceholderText("Search your event history"), { target: { value: "  AI\n model " } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByRole("link", { name: "Matching event" })).toHaveAttribute("href", "#event/event-1");
    expect(searchEvents).toHaveBeenCalledWith("AI model", null);
  });

  it("uses the backend opaque cursor when loading the next page", async () => {
    vi.mocked(searchEvents)
      .mockResolvedValueOnce({ next_cursor: "opaque-cursor", items: [{ id: "event-1", title: "First", overview: "Overview", state: "developing", display_time: "2026-08-16T13:00:00Z", updated_at: "2026-08-16T13:00:00Z", why_it_matters: "Why", new_claim_count: 0, conflict_count: 0, topics: [], saved: false }] })
      .mockResolvedValueOnce({ next_cursor: null, items: [{ id: "event-2", title: "Second", overview: "Overview", state: "developing", display_time: "2026-08-16T12:00:00Z", updated_at: "2026-08-16T12:00:00Z", why_it_matters: "Why", new_claim_count: 0, conflict_count: 0, topics: [], saved: false }] });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><SearchOverlay onClose={() => undefined} open /></QueryClientProvider>);

    fireEvent.change(screen.getByPlaceholderText("Search your event history"), { target: { value: "AI" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByRole("link", { name: "First" });
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    await screen.findByRole("link", { name: "Second" });
    expect(searchEvents).toHaveBeenLastCalledWith("AI", "opaque-cursor");
  });

  it("keeps the first page visible when loading the next page fails", async () => {
    vi.mocked(searchEvents)
      .mockResolvedValueOnce({ next_cursor: "opaque-cursor", items: [{ id: "event-1", title: "First page result", overview: "Overview", state: "developing", display_time: "2026-08-16T13:00:00Z", updated_at: "2026-08-16T13:00:00Z", why_it_matters: "Why", new_claim_count: 0, conflict_count: 0, topics: [], saved: false }] })
      .mockRejectedValueOnce(new Error("next page failed"));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><SearchOverlay onClose={() => undefined} open /></QueryClientProvider>);

    fireEvent.change(screen.getByPlaceholderText("Search your event history"), { target: { value: "AI" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByRole("link", { name: "First page result" });
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("We could not load more results.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "First page result" })).toBeInTheDocument();
    expect(screen.queryByText("We could not search your event history.")).not.toBeInTheDocument();
  });
});
