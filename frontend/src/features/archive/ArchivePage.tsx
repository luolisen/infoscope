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

  if (archive.isPending) return <main className="main-content archive-page"><p className="editorial-label">ARCHIVE / LOADING</p><p>正在打开历史 Event…</p></main>;
  if (archive.isError && archive.data === undefined) return <main className="main-content archive-page"><p className="editorial-label">ARCHIVE / UNAVAILABLE</p><p role="alert">无法加载 Archive，请稍后重试。</p></main>;
  if (!archive.isPending && archive.data !== undefined && items.length === 0) return <main className="main-content archive-page"><p className="editorial-label">ARCHIVE</p><header className="archive-header"><h1>还没有历史 Event。</h1><p>Event 离开 NOW 或被保存后，会一直保留在这里。</p></header></main>;

  return <main className="main-content archive-page" id="archive"><p className="editorial-label">ARCHIVE</p><header className="archive-header"><h1>你保存的历史。</h1></header><section aria-label="Archived events" className="archive-list">{items.map((event) => <article className="archive-item" key={event.id}><p className="editorial-label">EVENT / {event.state}</p><h2><a href={`#event/${event.id}`}>{event.title}</a></h2><p>{event.overview}</p><p className="archive-why">{event.why_it_matters}</p><SaveButton eventId={event.id} onSaved={() => { void archive.refetch(); }} saved={event.saved} /></article>)}</section>{archive.isFetchNextPageError && <p className="auth-error" role="alert">无法加载更多 Archive Event。</p>}{archive.hasNextPage && <button className="text-button archive-more" disabled={archive.isFetchingNextPage} onClick={() => { void archive.fetchNextPage(); }} type="button">{archive.isFetchingNextPage ? "加载中…" : "加载更多"}</button>}</main>;
}
