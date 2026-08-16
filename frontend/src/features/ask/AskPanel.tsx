import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { askQueryKey, createAsk, fetchAsk } from "../../api/ask";
import { eventDetailQueryKey } from "../../api/events";
import { nowQueryKey } from "../../api/now";

type AskPanelProps = {
  selectedEventIds: string[];
  onClearSelection: () => void;
};

export function AskPanel({ selectedEventIds, onClearSelection }: AskPanelProps) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const [askId, setAskId] = useState<string | null>(null);
  const refreshedAskId = useRef<string | null>(null);
  const create = useMutation({ mutationFn: ({ eventIds, text }: { eventIds: string[]; text: string }) => createAsk(eventIds, text) });
  const ask = useQuery({
    queryKey: askId === null ? ["ask", "idle"] : askQueryKey(askId),
    queryFn: () => fetchAsk(askId!),
    enabled: askId !== null,
    refetchInterval: (query) => query.state.data?.status === "pending" || query.state.data?.status === "running" ? 1_500 : false,
  });

  useEffect(() => {
    if (ask.data?.status !== "completed" || ask.data.ask_id === refreshedAskId.current) return;

    void queryClient.invalidateQueries({ queryKey: nowQueryKey });
    for (const eventId of ask.data.result.updated_event_ids) {
      void queryClient.invalidateQueries({ queryKey: eventDetailQueryKey(eventId) });
    }
    refreshedAskId.current = ask.data.ask_id;
  }, [ask.data, queryClient]);

  if (selectedEventIds.length === 0) return null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = question.trim();
    if (text.length === 0 || create.isPending) return;

    create.mutate({ eventIds: selectedEventIds, text }, {
      onSuccess: (accepted) => {
        setAskId(accepted.ask_id);
        setQuestion("");
        refreshedAskId.current = null;
      },
    });
  }

  const completed = ask.data?.status === "completed" ? ask.data.result : null;
  const failed = ask.data?.status === "failed" ? ask.data.error : null;
  const isPolling = ask.data?.status === "pending" || ask.data?.status === "running";

  return (
    <section className="ask-panel" aria-labelledby="ask-heading">
      <p className="editorial-label">ASK</p>
      <h2 id="ask-heading">Compare the selected events</h2>
      <p className="ask-selection">{selectedEventIds.length} selected event{selectedEventIds.length === 1 ? "" : "s"}. <button className="text-button" onClick={onClearSelection} type="button">Clear selection</button></p>
      <form className="ask-form" onSubmit={submit}>
        <label htmlFor="ask-question">Question</label>
        <textarea id="ask-question" maxLength={2000} onChange={(event) => setQuestion(event.target.value)} placeholder="What do you want to understand?" required value={question} />
        <button className="auth-submit" disabled={create.isPending || question.trim().length === 0} type="submit">{create.isPending ? "Starting Ask…" : "Ask Infoscope"}</button>
      </form>
      {create.isError && <p className="auth-error" role="alert">We could not start this Ask. Please try again.</p>}
      {(ask.isPending || isPolling) && <p className="ask-progress" role="status">Researching the current event record…</p>}
      {ask.isError && <p className="auth-error" role="alert">We could not check this Ask. Please try again.</p>}
      {failed !== null && <p className="auth-error" role="alert">{failed.message}</p>}
      {completed !== null && <div className="ask-result"><p className="editorial-label">ANSWER</p><p>{completed.answer}</p>{completed.updated_event_ids.length > 0 && <p className="ask-updated" role="status">事件信息已补充。NOW and the updated event details have been refreshed.</p>}</div>}
    </section>
  );
}
