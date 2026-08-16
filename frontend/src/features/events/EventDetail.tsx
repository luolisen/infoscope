import { useQuery } from "@tanstack/react-query";

import { eventDetailQueryKey, fetchEventDetail } from "../../api/events";
import { SaveButton } from "./SaveButton";

type EventDetailProps = {
  eventId: string;
  onBack: () => void;
  selectedEvents: { id: string; title: string }[];
  onToggleEventSelection: (event: { id: string; title: string }) => void;
};

function formatTime(value: string | null) {
  if (value === null) return "Time not published";

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

export function EventDetail({ eventId, onBack, selectedEvents, onToggleEventSelection }: EventDetailProps) {
  const detail = useQuery({
    queryKey: eventDetailQueryKey(eventId),
    queryFn: () => fetchEventDetail(eventId),
  });

  if (detail.isPending) {
    return <main className="main-content detail-page"><p className="editorial-label">EVENT / LOADING</p><p>Loading the current event record…</p></main>;
  }

  if (detail.isError) {
    return <main className="main-content detail-page"><p className="editorial-label">EVENT / UNAVAILABLE</p><p role="alert">We could not load this event. Please return to NOW and try again.</p><button className="text-button detail-back" onClick={onBack} type="button">Back to NOW</button></main>;
  }

  const event = detail.data;
  const claimsById = new Map(event.claims.map((claim) => [claim.id, claim]));
  const evidenceById = new Map(event.evidence.map((evidence) => [evidence.id, evidence]));

  return (
    <main className="main-content detail-page">
      <button className="text-button detail-back" onClick={onBack} type="button">← NOW</button>
      <header className="detail-header">
        <p className="editorial-label">EVENT / {event.state}</p>
        <h1>{event.title}</h1>
        <p className="detail-overview">{event.overview}</p>
        <p className="event-meta">Updated {formatTime(event.updated_at)} · Display time {formatTime(event.display_time)}</p>
        <button className="text-button detail-select" disabled={!selectedEvents.some((selected) => selected.id === event.id) && selectedEvents.length === 8} onClick={() => onToggleEventSelection({ id: event.id, title: event.title })} type="button">{selectedEvents.some((selected) => selected.id === event.id) ? "Remove from Ask selection" : "Add to Ask selection"}</button>
        <SaveButton eventId={event.id} saved={event.saved} />
      </header>

      <section className="detail-section detail-analysis" aria-labelledby="analysis-heading">
        <p className="editorial-label">BASE ANALYSIS / {event.base_analysis.importance}</p>
        <h2 id="analysis-heading">What this event is</h2>
        <p>{event.base_analysis.summary}</p>
        <dl className="analysis-meta">
          <div><dt>Type</dt><dd>{event.base_analysis.event_type}</dd></div>
          <div><dt>Topics</dt><dd>{event.topics.join(" · ") || "Unclassified"}</dd></div>
        </dl>
        {event.base_analysis.entities.length > 0 && <p className="entity-list">{event.base_analysis.entities.map((entity) => `${entity.name} (${entity.entity_type})`).join(" · ")}</p>}
      </section>

      <section className="detail-section" aria-labelledby="timeline-heading">
        <p className="editorial-label">TIMELINE</p>
        <h2 id="timeline-heading">How it developed</h2>
        {event.timeline.length === 0 ? <p className="detail-empty">No timeline entries are available yet.</p> : <ol className="timeline-list">{event.timeline.map((entry) => <li key={entry.id}><time dateTime={entry.occurred_at}>{formatTime(entry.occurred_at)}</time><div><p>{entry.summary}</p>{entry.claim_ids.length > 0 && <p className="detail-links">Linked claims: {entry.claim_ids.map((id) => claimsById.get(id)?.text).filter((text): text is string => text !== undefined).join(" · ")}</p>}</div></li>)}</ol>}
      </section>

      <section className="detail-section" aria-labelledby="claims-heading">
        <p className="editorial-label">CLAIMS</p>
        <h2 id="claims-heading">Current factual record</h2>
        {event.claims.length === 0 ? <p className="detail-empty">No claims are available yet.</p> : <ul className="detail-list">{event.claims.map((claim) => <li key={claim.id}><p className="editorial-label">{claim.state}</p><p>{claim.text}</p>{claim.evidence_ids.length > 0 && <div className="detail-relations"><p>Supporting evidence</p><ul>{claim.evidence_ids.map((id) => <li key={id}>{evidenceById.get(id)?.excerpt}</li>)}</ul></div>}</li>)}</ul>}
      </section>

      <section className="detail-section" aria-labelledby="conflicts-heading">
        <p className="editorial-label">CONFLICTS</p>
        <h2 id="conflicts-heading">What remains contested</h2>
        {event.conflicts.length === 0 ? <p className="detail-empty">No unresolved conflicts are recorded.</p> : <ul className="detail-list">{event.conflicts.map((conflict) => <li key={conflict.id}><p>{conflict.summary}</p><div className="detail-relations"><p>Conflicting claims</p><ul>{conflict.claim_ids.map((id) => <li key={id}>{claimsById.get(id)?.text}</li>)}</ul>{conflict.evidence_ids.length > 0 && <><p>Related evidence</p><ul>{conflict.evidence_ids.map((id) => <li key={id}>{evidenceById.get(id)?.excerpt}</li>)}</ul></>}</div></li>)}</ul>}
      </section>

      <section className="detail-section" aria-labelledby="evidence-heading">
        <p className="editorial-label">EVIDENCE</p>
        <h2 id="evidence-heading">Source material</h2>
        {event.evidence.length === 0 ? <p className="detail-empty">No evidence is available yet.</p> : <ul className="detail-list evidence-list">{event.evidence.map((evidence) => <li key={evidence.id}><p className="editorial-label">{evidence.platform} / {evidence.visibility}</p><p>{evidence.excerpt}</p><p className="detail-links">{formatTime(evidence.published_at)}{evidence.author_name !== null ? ` · ${evidence.author_name}` : ""}</p>{evidence.url !== null && <a href={evidence.url} rel="noreferrer" target="_blank">Open public source</a>}</li>)}</ul>}
      </section>

      <section className="detail-section detail-why" aria-labelledby="why-heading">
        <p className="editorial-label">WHY IT MATTERS</p>
        <h2 id="why-heading">The current context</h2>
        <p>{event.why_it_matters}</p>
      </section>
    </main>
  );
}
