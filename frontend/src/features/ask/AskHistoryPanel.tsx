import { useRef, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";

import { askHistoryQueryKey, fetchAskHistory } from "../../api/ask";
import { ChevronIcon, PinIcon } from "../../components/Icons";

const PIN_KEY = "infoscope.ask-history.pinned";

function readPinned() {
  try {
    return window.localStorage.getItem(PIN_KEY) === "true";
  } catch {
    return false;
  }
}

function statusLabel(status: string) {
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "running") return "处理中";
  return "等待中";
}

export function AskHistoryPanel() {
  const [pinned, setPinned] = useState(readPinned);
  const [expanded, setExpanded] = useState(readPinned);
  const [hovered, setHovered] = useState(false);
  const [focusWithin, setFocusWithin] = useState(false);
  const [manuallyCollapsed, setManuallyCollapsed] = useState(false);
  const panelRef = useRef<HTMLElement>(null);
  const history = useInfiniteQuery({
    queryKey: askHistoryQueryKey,
    queryFn: ({ pageParam }) => fetchAskHistory(20, pageParam ?? undefined),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const items = history.data?.pages.flatMap((page) => page.items) ?? [];
  const persistentlyExpanded = pinned || expanded;
  const visible = persistentlyExpanded || (!manuallyCollapsed && (hovered || focusWithin));

  const persistPin = (next: boolean) => {
    setPinned(next);
    try {
      window.localStorage.setItem(PIN_KEY, String(next));
    } catch {
      // Ignore unavailable browser storage.
    }
  };

  const togglePinned = () => {
    const next = !pinned;
    persistPin(next);
    setExpanded(next);
    setManuallyCollapsed(!next);
  };

  const toggleExpanded = () => {
    if (persistentlyExpanded) {
      persistPin(false);
      setExpanded(false);
      setManuallyCollapsed(true);
      return;
    }
    setManuallyCollapsed(false);
    setExpanded(true);
  };

  return (
    <aside
      aria-label="Ask 历史"
      className={`ask-history${visible ? " ask-history--expanded" : ""}${pinned ? " ask-history--pinned" : ""}`}
      onBlur={(event) => {
        if (!panelRef.current?.contains(event.relatedTarget)) setFocusWithin(false);
      }}
      onFocus={() => {
        setFocusWithin(true);
        setManuallyCollapsed(false);
      }}
      onMouseEnter={() => {
        setHovered(true);
        setManuallyCollapsed(false);
      }}
      onMouseLeave={() => setHovered(false)}
      ref={panelRef}
    >
      <div className="ask-history__toolbar">
        <button
          aria-expanded={visible}
          aria-label={persistentlyExpanded ? "折叠 Ask 历史" : "展开 Ask 历史"}
          className="icon-button ask-history__toggle"
          onClick={toggleExpanded}
          type="button"
        >
          <ChevronIcon className="action-icon" direction={visible ? "right" : "left"} />
        </button>
        {visible && <span className="ask-history__title">历史提问</span>}
        {visible && <button aria-pressed={pinned} aria-label={pinned ? "取消固定 Ask 历史" : "固定 Ask 历史"} className="icon-button ask-history__pin" onClick={togglePinned} title={pinned ? "取消固定" : "固定历史"} type="button"><PinIcon className="action-icon" filled={pinned} /></button>}
      </div>
      {visible && (
        <div className="ask-history__body" aria-live="polite">
          {history.isPending && <p className="ask-history__empty">正在加载历史…</p>}
          {history.isError && <p className="ask-history__empty" role="alert">历史暂时无法加载。</p>}
          {history.data !== undefined && items.length === 0 && <p className="ask-history__empty">还没有历史提问。</p>}
          {items.map((item) => (
            <article className="ask-history__item" key={item.ask_id}>
              <p className="editorial-label">{statusLabel(item.status)}</p>
              <p className="ask-history__question">{item.question}</p>
              {item.answer && <p className="ask-history__answer">{item.answer}</p>}
            </article>
          ))}
          {history.isFetchNextPageError && <p className="ask-history__empty" role="alert">无法加载更多历史。</p>}
          {history.hasNextPage && <button className="text-button ask-history__more" disabled={history.isFetchingNextPage} onClick={() => { void history.fetchNextPage(); }} type="button">{history.isFetchingNextPage ? "加载中…" : "加载更多"}</button>}
        </div>
      )}
    </aside>
  );
}
