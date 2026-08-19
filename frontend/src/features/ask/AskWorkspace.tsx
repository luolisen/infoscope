import { useState } from "react";

import type { components } from "../../api/schema";
import { AskPanel } from "./AskPanel";
import { AskHistoryPanel } from "./AskHistoryPanel";

type EventSelection = { id: string; title: string };
type AskHistoryItem = components["schemas"]["AskHistoryItem"];

type AskWorkspaceProps = {
  selectedEvents: EventSelection[];
  onClearSelection: () => void;
};

export function AskWorkspace({ selectedEvents, onClearSelection }: AskWorkspaceProps) {
  const [historyItem, setHistoryItem] = useState<AskHistoryItem | null>(null);

  return (
    <main className="main-content ask-workspace" aria-label={historyItem === null && selectedEvents.length > 0 ? "Ask 工作区" : undefined} aria-labelledby={historyItem !== null || selectedEvents.length === 0 ? "ask-workspace-heading" : undefined}>
      <AskHistoryPanel onSelect={setHistoryItem} selectedAskId={historyItem?.ask_id} />
      {historyItem === null ? <>
        {selectedEvents.length === 0 && <header className="ask-workspace__hero">
          <p className="editorial-label">ASK</p>
          <h1 id="ask-workspace-heading">观澜能帮你做什么？</h1>
          <p>选择一个或多个 Event，再提出你想理解的问题。</p>
        </header>}
        <AskPanel onClearSelection={onClearSelection} selectedEvents={selectedEvents} workspace />
      </> : <section className="ask-history-detail" aria-labelledby="ask-workspace-heading">
        <div className="ask-history-detail__meta">
          <p className="editorial-label">历史提问</p>
          <button className="ask-new-question" onClick={() => setHistoryItem(null)} type="button"><span aria-hidden="true" className="ask-new-question__mark">＋</span><span>新增提问</span></button>
        </div>
        <h1 id="ask-workspace-heading">{historyItem.question}</h1>
        <p className="ask-history-detail__context">涉及 {historyItem.event_ids.length} 个 Event · {historyItem.status === "completed" ? "已完成" : historyItem.status === "failed" ? "失败" : "处理中"}</p>
        <details className="ask-thinking ask-thinking--complete"><summary>已思考 {historyItem.thinking_seconds} 秒</summary><ol>{historyItem.process_stages.map((stage) => <li key={stage}>{stage === "comparing" ? "已比较 Event 数据库" : stage === "researching" ? "已获取并规范化补充信息" : stage === "reconciling" ? "已复核 Event 事实" : "已组织回答"}</li>)}</ol></details>
        {historyItem.answer ? <div className="ask-history-detail__answer"><p className="editorial-label">回答</p><p>{historyItem.answer}</p></div> : <p className="ask-history-detail__empty">{historyItem.status === "failed" ? "该轮提问未能完成。" : "该轮提问仍在处理中。"}</p>}
        {(historyItem.updated_event_ids?.length ?? 0) > 0 && <p className="ask-updated">该轮补充了 Event 信息。</p>}
      </section>}
    </main>
  );
}
