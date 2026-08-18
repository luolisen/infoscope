import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { askHistoryQueryKey, fetchAskHistory } from "../../api/ask";

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
  const history = useQuery({
    queryKey: askHistoryQueryKey,
    queryFn: () => fetchAskHistory(),
  });

  const togglePinned = () => {
    const next = !pinned;
    setPinned(next);
    setExpanded(next || expanded);
    try {
      window.localStorage.setItem(PIN_KEY, String(next));
    } catch {
      // Ignore unavailable browser storage.
    }
  };

  return (
    <aside
      aria-label="Ask 历史"
      className={`ask-history${expanded ? " ask-history--expanded" : ""}${pinned ? " ask-history--pinned" : ""}`}
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => { if (!pinned) setExpanded(false); }}
    >
      <div className="ask-history__toolbar">
        <button
          aria-expanded={expanded}
          aria-label={expanded ? "折叠 Ask 历史" : "展开 Ask 历史"}
          className="icon-button ask-history__toggle"
          onClick={() => setExpanded((value) => !value)}
          type="button"
        >
          <span aria-hidden="true">{expanded ? "‹" : "›"}</span>
        </button>
        {expanded && <span className="ask-history__title">历史提问</span>}
        {expanded && <button aria-pressed={pinned} aria-label={pinned ? "取消固定 Ask 历史" : "固定 Ask 历史"} className="icon-button ask-history__pin" onClick={togglePinned} type="button"><span aria-hidden="true">{pinned ? "●" : "○"}</span></button>}
      </div>
      {expanded && (
        <div className="ask-history__body" aria-live="polite">
          {history.isPending && <p className="ask-history__empty">正在加载历史…</p>}
          {history.isError && <p className="ask-history__empty" role="alert">历史暂时无法加载。</p>}
          {history.data?.items.length === 0 && <p className="ask-history__empty">还没有历史提问。</p>}
          {history.data?.items.map((item) => (
            <article className="ask-history__item" key={item.ask_id}>
              <p className="editorial-label">{statusLabel(item.status)}</p>
              <p className="ask-history__question">{item.question}</p>
              {item.answer && <p className="ask-history__answer">{item.answer}</p>}
            </article>
          ))}
        </div>
      )}
    </aside>
  );
}
