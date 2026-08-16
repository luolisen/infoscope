import { useInfiniteQuery } from "@tanstack/react-query";

import { fetchArchive } from "../../api/archiveSearch";
import { SaveButton } from "../events/SaveButton";

export function ArchivePage() {
  const archive = useInfiniteQuery({
    queryKey: ["archive"],
    queryFn: ({ pageParam }) => fetchArchive(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const items = archive.data?.pages.flatMap((page) => page.items) ?? [];

  if (archive.isPending) return <main className="main-content archive-page"><p className="editorial-label">ARCHIVE / LOADING</p><p>Opening your historical event record…</p></main>;
  if (archive.isError) return <main className="main-content archive-page"><p className="editorial-label">ARCHIVE / UNAVAILABLE</p><p role="alert">We could not load Archive. Please try again.</p></main>;
  if (!archive.isPending && !archive.isError && items.length === 0) return <main className="main-content archive-page"><p className="editorial-label">ARCHIVE</p><header className="archive-header"><h1>No historical events yet.</h1><p>Events will remain here once they leave NOW, or when you save them.</p></header></main>;

  return <main className="main-content archive-page" id="archive"><p className="editorial-label">ARCHIVE</p><header className="archive-header"><h1>What you have kept.</h1></header><section aria-label="Archived events" className="archive-list">{items.map((event) => <article className="archive-item" key={event.id}><p className="editorial-label">EVENT / {event.state}</p><h2><a href={`#event/${event.id}`}>{event.title}</a></h2><p>{event.overview}</p><p className="archive-why">{event.why_it_matters}</p><SaveButton eventId={event.id} onSaved={() => { void archive.refetch(); }} saved={event.saved} /></article>)}</section>{archive.isFetchNextPageError && <p className="auth-error" role="alert">We could not load more Archive events.</p>}{archive.hasNextPage && <button className="text-button archive-more" disabled={archive.isFetchingNextPage} onClick={() => { void archive.fetchNextPage(); }} type="button">{archive.isFetchingNextPage ? "Loading…" : "Load more"}</button>}</main>;
}
