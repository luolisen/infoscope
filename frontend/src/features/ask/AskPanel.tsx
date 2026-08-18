import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { askHistoryQueryKey, askQueryKey, createAsk, fetchAsk } from "../../api/ask";
import { eventDetailQueryKey } from "../../api/events";
import { nowQueryKey } from "../../api/now";
import { SendIcon } from "../../components/Icons";

type AskPanelProps = {
  selectedEvents: { id: string; title: string }[];
  onClearSelection: () => void;
  workspace?: boolean;
};

export function AskPanel({ selectedEvents, onClearSelection, workspace = false }: AskPanelProps) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const [askId, setAskId] = useState<string | null>(null);
  const [submittedEvents, setSubmittedEvents] = useState<{ id: string; title: string }[] | null>(null);
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

  useEffect(() => {
    if (ask.data?.status !== "completed" && ask.data?.status !== "failed") return;
    void queryClient.invalidateQueries({ queryKey: askHistoryQueryKey });
  }, [ask.data?.ask_id, ask.data?.status, queryClient]);

  const isTerminal = ask.data?.status === "completed" || ask.data?.status === "failed";
  const isActive = askId !== null && !isTerminal;
  const displayEvents = askId === null ? selectedEvents : submittedEvents ?? selectedEvents;

  if (displayEvents.length === 0 && !workspace) return null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = question.trim();
    if (text.length === 0 || create.isPending || askId !== null) return;

    create.mutate({ eventIds: selectedEvents.map((eventToAsk) => eventToAsk.id), text }, {
      onSuccess: (accepted) => {
        setAskId(accepted.ask_id);
        setSubmittedEvents(selectedEvents);
        setQuestion("");
        refreshedAskId.current = null;
        void queryClient.invalidateQueries({ queryKey: askHistoryQueryKey });
      },
    });
  }

  const completed = ask.data?.status === "completed" ? ask.data.result : null;
  const failed = ask.data?.status === "failed" ? ask.data.error : null;

  function startAnotherAsk() {
    setAskId(null);
    setSubmittedEvents(null);
    setQuestion("");
    refreshedAskId.current = null;
    create.reset();
  }

  return (
    <section className={`ask-panel${workspace ? " ask-panel--workspace" : ""}`} aria-labelledby="ask-heading">
      {!workspace && <p className="editorial-label">ASK</p>}
      {!workspace && <h2 id="ask-heading">询问观澜</h2>}
      <p className="ask-selection">{displayEvents.length === 0 ? "请选择至少一个 Event" : `${displayEvents.length} 个 Event：${displayEvents.map((eventToAsk) => eventToAsk.title).join(" · ")}.`} {!isActive && displayEvents.length > 0 && <button className="text-button" onClick={onClearSelection} type="button">清除选择</button>}</p>
      <form className="ask-form" onSubmit={submit}>
        <label className="visually-hidden" htmlFor="ask-question">你的问题</label>
        <textarea disabled={askId !== null} id="ask-question" maxLength={2000} onChange={(event) => setQuestion(event.target.value)} placeholder="你想了解什么？" required value={question} />
        {(question.trim().length > 0 || create.isPending || isActive) && <button aria-busy={create.isPending || isActive} aria-label={isActive ? "处理中" : "发送问题"} className={`auth-submit ask-send-button${create.isPending || isActive ? " ask-send-button--busy" : ""}`} disabled={create.isPending || askId !== null || question.trim().length === 0 || selectedEvents.length === 0} title={isActive ? "处理中" : "发送问题"} type="submit"><SendIcon className="action-icon" /></button>}
      </form>
      {create.isError && <p className="auth-error" role="alert">无法开始 Ask，请稍后重试。</p>}
      {isActive && <p className="ask-progress" role="status">正在整理相关信息…</p>}
      {ask.isError && <><p className="auth-error" role="alert">无法检查该 Ask，请稍后重试。</p><button className="text-button" onClick={() => { void ask.refetch(); }} type="button">重试状态检查</button></>}
      {failed !== null && <p className="auth-error" role="alert">{failed.message}</p>}
      {completed !== null && <div className="ask-result"><p className="editorial-label">回答</p><p>{completed.answer}</p><p className="ask-answer-boundary">分析回答，不作为 Evidence。</p>{completed.updated_event_ids.length > 0 && <p className="ask-updated" role="status">事件信息已补充，NOW 与事件详情已刷新。</p>}</div>}
      {isTerminal && <button className="text-button ask-another" onClick={startAnotherAsk} type="button">再问一个问题</button>}
    </section>
  );
}
