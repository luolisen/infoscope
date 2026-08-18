import { useEffect, useRef, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";

import { searchEvents, searchQueryKey } from "../../api/archiveSearch";
import { SaveButton } from "../events/SaveButton";

type SearchOverlayProps = { open: boolean; onClose: () => void };

export function SearchOverlay({ open, onClose }: SearchOverlayProps) {
  const dialogRef = useRef<HTMLFormElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
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
    inputRef.current?.focus();
    const handleKeyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handleKeyboard);
    return () => window.removeEventListener("keydown", handleKeyboard);
  }, [onClose, open]);

  if (!open) return null;
  return <div aria-modal="true" className="search-overlay" role="dialog" aria-label="搜索 Event"><form className="search-dialog" onSubmit={(event) => { event.preventDefault(); const query = text.trim().replace(/\s+/g, " "); if (query) setSubmitted(query); }} ref={dialogRef}><div className="search-dialog__bar"><label htmlFor="global-search">搜索 Event</label><button aria-label="关闭搜索" className="icon-button icon-button--close" onClick={onClose} type="button"><span aria-hidden="true">×</span></button></div><input id="global-search" onChange={(event) => setText(event.target.value)} placeholder="搜索历史 Event" ref={inputRef} value={text} /><button className="auth-submit" type="submit">搜索</button>{isSearching && <p role="status">搜索中…</p>}{search.isError && search.data === undefined && <p className="auth-error" role="alert">暂时无法搜索历史 Event。</p>}{search.data !== undefined && <section aria-label="搜索结果" className="search-results">{results.length === 0 ? <p>没有匹配的历史 Event。</p> : results.map((event) => <article key={event.id}><h2><a href={`#event/${event.id}`} onClick={onClose}>{event.title}</a></h2><p>{event.overview}</p><p>{event.why_it_matters}</p><SaveButton eventId={event.id} saved={event.saved} /></article>)}{search.hasNextPage && <button className="text-button" disabled={search.isFetchingNextPage} onClick={() => search.fetchNextPage()} type="button">{search.isFetchingNextPage ? "加载中…" : "加载更多"}</button>}{search.isFetchNextPageError && <p className="auth-error" role="alert">无法加载更多结果。</p>}</section>}</form></div>;
}
