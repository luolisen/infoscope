import { useEffect, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";

import { searchEvents, searchQueryKey } from "../../api/archiveSearch";
import { SaveButton } from "../events/SaveButton";

type SearchOverlayProps = { open: boolean; onClose: () => void };

export function SearchOverlay({ open, onClose }: SearchOverlayProps) {
  const [text, setText] = useState("");
  const [submitted, setSubmitted] = useState("");
  const search = useInfiniteQuery({
    queryKey: searchQueryKey(submitted, null),
    queryFn: ({ pageParam }) => searchEvents(submitted, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled: submitted.length > 0,
  });
  const results = search.data?.pages.flatMap((page) => page.items) ?? [];
  const isSearching = submitted.length > 0 && search.data === undefined && (search.isPending || search.isFetching);

  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose, open]);

  if (!open) return null;
  return <div aria-modal="true" className="search-overlay" role="dialog" aria-label="Search events"><form className="search-dialog" onSubmit={(event) => { event.preventDefault(); const query = text.trim().replace(/\s+/g, " "); if (query) setSubmitted(query); }}><div className="search-dialog__bar"><label htmlFor="global-search">Search events</label><button className="text-button" onClick={onClose} type="button">Close</button></div><input autoFocus id="global-search" onChange={(event) => setText(event.target.value)} placeholder="Search your event history" value={text} /><button className="auth-submit" type="submit">Search</button>{isSearching && <p role="status">Searching…</p>}{search.isError && search.data === undefined && <p className="auth-error" role="alert">We could not search your event history.</p>}{search.data !== undefined && <section aria-label="Search results" className="search-results">{results.length === 0 ? <p>No matching historical events.</p> : results.map((event) => <article key={event.id}><h2><a href={`#event/${event.id}`} onClick={onClose}>{event.title}</a></h2><p>{event.overview}</p><p>{event.why_it_matters}</p><SaveButton eventId={event.id} saved={event.saved} /></article>)}{search.hasNextPage && <button className="text-button" disabled={search.isFetchingNextPage} onClick={() => search.fetchNextPage()} type="button">{search.isFetchingNextPage ? "Loading more…" : "Load more"}</button>}{search.isFetchNextPageError && <p className="auth-error" role="alert">We could not load more results.</p>}</section>}</form></div>;
}
