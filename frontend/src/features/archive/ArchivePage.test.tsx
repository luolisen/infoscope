import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/archiveSearch", () => ({ fetchArchive: vi.fn() }));
vi.mock("../events/SaveButton", () => ({ SaveButton: () => <button type="button">Save event</button> }));

import { fetchArchive } from "../../api/archiveSearch";
import { ArchivePage } from "./ArchivePage";

afterEach(() => { cleanup(); vi.resetAllMocks(); });

function renderArchive() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><ArchivePage /></QueryClientProvider>);
}

describe("ArchivePage", () => {
  it("renders loading and the legal empty Archive", async () => {
    vi.mocked(fetchArchive).mockImplementation(() => new Promise(() => undefined));
    const view = renderArchive();
    expect(screen.getByText(/opening your historical event record/i)).toBeInTheDocument();

    view.unmount();
    vi.mocked(fetchArchive).mockResolvedValue({ items: [], next_cursor: null });
    renderArchive();
    expect(await screen.findByRole("heading", { name: /no historical events yet/i })).toBeInTheDocument();
  });

  it("keeps Backend event order and links items to Event Detail", async () => {
    vi.mocked(fetchArchive).mockResolvedValue({
      next_cursor: null,
      items: [
        { id: "event-2", title: "Second from Backend", overview: "Second overview", state: "developing", display_time: "2026-08-16T13:00:00Z", updated_at: "2026-08-16T13:00:00Z", why_it_matters: "Second why", new_claim_count: 0, conflict_count: 0, topics: [], saved: false },
        { id: "event-1", title: "First from Backend", overview: "First overview", state: "confirmed", display_time: "2026-08-16T12:00:00Z", updated_at: "2026-08-16T12:00:00Z", why_it_matters: "First why", new_claim_count: 1, conflict_count: 0, topics: [], saved: true },
      ],
    });
    renderArchive();

    expect(await screen.findByText("Second overview")).toBeInTheDocument();
    expect(screen.getAllByRole("link").map((link) => link.textContent)).toEqual(["Second from Backend", "First from Backend"]);
    expect(screen.getByRole("link", { name: "Second from Backend" })).toHaveAttribute("href", "#event/event-2");
  });
});
