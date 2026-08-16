import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/archiveSearch", () => ({ searchEvents: vi.fn(), searchQueryKey: (query: string) => ["search", "events", query] }));
vi.mock("../events/SaveButton", () => ({ SaveButton: () => null }));

import { searchEvents } from "../../api/archiveSearch";
import { SearchOverlay } from "./SearchOverlay";

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("SearchOverlay", () => {
  it("submits normalized text to the generated Search endpoint and links results", async () => {
    vi.mocked(searchEvents).mockResolvedValue({ next_cursor: null, items: [{ id: "event-1", title: "Matching event", overview: "Overview", state: "developing", display_time: "2026-08-16T13:00:00Z", updated_at: "2026-08-16T13:00:00Z", why_it_matters: "Why", new_claim_count: 0, conflict_count: 0, topics: [], saved: false }] });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><SearchOverlay onClose={() => undefined} open /></QueryClientProvider>);

    fireEvent.change(screen.getByPlaceholderText("Search your event history"), { target: { value: "  AI\n model " } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByRole("link", { name: "Matching event" })).toHaveAttribute("href", "#event/event-1");
    expect(searchEvents).toHaveBeenCalledWith("AI model", null);
  });
});
