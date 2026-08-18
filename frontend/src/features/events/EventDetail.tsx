import { useQuery } from "@tanstack/react-query";

import { eventDetailQueryKey, fetchEventDetail } from "../../api/events";
import {
  formatClaimState,
  formatEventState,
  formatEvidenceVisibility,
  formatImportance,
  formatUtcDateTime,
} from "../../formatters";
import { SaveButton } from "./SaveButton";

type EventDetailProps = {
  eventId: string;
  onAsk?: () => void;
  onBack: () => void;
  selectedEvents: { id: string; title: string }[];
  onToggleEventSelection: (event: { id: string; title: string }) => void;
};

export function EventDetail({ eventId, onAsk = () => undefined, onBack, selectedEvents, onToggleEventSelection }: EventDetailProps) {
  const detail = useQuery({
    queryKey: eventDetailQueryKey(eventId),
    queryFn: () => fetchEventDetail(eventId),
  });

  if (detail.isPending) {
    return <main className="main-content detail-page"><p className="editorial-label">EVENT / 加载中</p><p>正在加载当前事件记录…</p></main>;
  }

  if (detail.isError) {
    return <main className="main-content detail-page"><p className="editorial-label">EVENT / 不可用</p><p role="alert">无法加载该事件，请返回 NOW 重试。</p><button className="text-button detail-back" onClick={onBack} type="button">返回 NOW</button></main>;
  }

  const event = detail.data;
  const selected = selectedEvents.some((selectedEvent) => selectedEvent.id === event.id);
  const claimsById = new Map(event.claims.map((claim) => [claim.id, claim]));
  const evidenceById = new Map(event.evidence.map((evidence) => [evidence.id, evidence]));

  return (
    <main className="main-content detail-page">
      <button className="text-button detail-back" onClick={onBack} type="button">← NOW</button>
      <header className="detail-header">
        <p className="editorial-label">EVENT / {formatEventState(event.state)}</p>
        <h1>{event.title}</h1>
        <p className="detail-overview">{event.overview}</p>
        <p className="event-meta">更新于 {formatUtcDateTime(event.updated_at)} · 展示时间 {formatUtcDateTime(event.display_time)}</p>
        <div className="detail-actions">
          <button className="detail-ask-button" onClick={() => { if (!selected) onToggleEventSelection({ id: event.id, title: event.title }); onAsk(); }} type="button">询问这个事件</button>
          <button aria-pressed={selected} className="detail-select-button" disabled={!selected && selectedEvents.length === 8} onClick={() => onToggleEventSelection({ id: event.id, title: event.title })} type="button">{selected ? "从询问选择中移除" : "加入询问选择"}</button>
          <SaveButton eventId={event.id} saved={event.saved} />
        </div>
      </header>

      <section className="detail-section detail-analysis" aria-labelledby="analysis-heading">
        <p className="editorial-label">BASE ANALYSIS / {formatImportance(event.base_analysis.importance)}</p>
        <h2 id="analysis-heading">事件概览</h2>
        <p>{event.base_analysis.summary}</p>
        <dl className="analysis-meta">
          <div><dt>类型</dt><dd>{event.base_analysis.event_type}</dd></div>
          <div><dt>主题</dt><dd>{event.topics.join(" · ") || "未分类"}</dd></div>
        </dl>
        {event.base_analysis.entities.length > 0 && <p className="entity-list">{event.base_analysis.entities.map((entity) => `${entity.name} (${entity.entity_type})`).join(" · ")}</p>}
      </section>

      <section className="detail-section" aria-labelledby="timeline-heading">
        <p className="editorial-label">TIMELINE</p>
        <h2 id="timeline-heading">事件如何发展</h2>
        {event.timeline.length === 0 ? <p className="detail-empty">暂时没有时间线记录。</p> : <ol className="timeline-list">{event.timeline.map((entry) => <li key={entry.id}><time dateTime={entry.occurred_at}>{formatUtcDateTime(entry.occurred_at)}</time><div><p>{entry.summary}</p>{entry.claim_ids.length > 0 && <p className="detail-links">关联主张：{entry.claim_ids.map((id) => claimsById.get(id)?.text).filter((text): text is string => text !== undefined).join(" · ")}</p>}</div></li>)}</ol>}
      </section>

      <section className="detail-section" aria-labelledby="claims-heading">
        <p className="editorial-label">CLAIMS</p>
        <h2 id="claims-heading">当前事实记录</h2>
        {event.claims.length === 0 ? <p className="detail-empty">暂时没有主张记录。</p> : <ul className="detail-list">{event.claims.map((claim) => <li key={claim.id}><p className="editorial-label">{formatClaimState(claim.state)}</p><p>{claim.text}</p>{claim.evidence_ids.length > 0 && <div className="detail-relations"><p>支持证据</p><ul>{claim.evidence_ids.map((id) => <li key={id}>{evidenceById.get(id)?.excerpt}</li>)}</ul></div>}</li>)}</ul>}
      </section>

      <section className="detail-section" aria-labelledby="conflicts-heading">
        <p className="editorial-label">CONFLICTS</p>
        <h2 id="conflicts-heading">仍待核实的分歧</h2>
        {event.conflicts.length === 0 ? <p className="detail-empty">暂时没有未解决的冲突。</p> : <ul className="detail-list">{event.conflicts.map((conflict) => <li key={conflict.id}><p>{conflict.summary}</p><div className="detail-relations"><p>冲突主张</p><ul>{conflict.claim_ids.map((id) => <li key={id}>{claimsById.get(id)?.text}</li>)}</ul>{conflict.evidence_ids.length > 0 && <><p>相关证据</p><ul>{conflict.evidence_ids.map((id) => <li key={id}>{evidenceById.get(id)?.excerpt}</li>)}</ul></>}</div></li>)}</ul>}
      </section>

      <section className="detail-section" aria-labelledby="evidence-heading">
        <p className="editorial-label">EVIDENCE</p>
        <h2 id="evidence-heading">来源材料</h2>
        {event.evidence.length === 0 ? <p className="detail-empty">暂时没有证据。</p> : <ul className="detail-list evidence-list">{event.evidence.map((evidence) => <li key={evidence.id}><p className="editorial-label">{evidence.platform} / {formatEvidenceVisibility(evidence.visibility)}</p><p>{evidence.excerpt}</p><p className="detail-links">{formatUtcDateTime(evidence.published_at)}{evidence.author_name !== null ? ` · ${evidence.author_name}` : ""}</p>{evidence.url !== null && <a href={evidence.url} rel="noreferrer" target="_blank">打开公开来源</a>}</li>)}</ul>}
      </section>

      <section className="detail-section detail-why" aria-labelledby="why-heading">
        <p className="editorial-label">WHY IT MATTERS</p>
        <h2 id="why-heading">当前语境</h2>
        <p>{event.why_it_matters}</p>
      </section>
    </main>
  );
}
