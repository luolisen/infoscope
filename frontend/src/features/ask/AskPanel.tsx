import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { components } from "../../api/schema";
import { askHistoryQueryKey, askQueryKey, createAsk, fetchAsk, fetchAskHistory } from "../../api/ask";
import { eventDetailQueryKey } from "../../api/events";
import { nowQueryKey } from "../../api/now";
import { SendIcon } from "../../components/Icons";

type AskHistoryItem = components["schemas"]["AskHistoryItem"];
type AskProgress = components["schemas"]["AskProgress"];

type AskPanelProps = {
  selectedEvents: { id: string; title: string }[];
  onClearSelection: () => void;
  workspace?: boolean;
};

const stageLabels: Record<AskProgress["stage"], string> = {
  comparing: "正在比较 Event 数据库",
  researching: "正在获取并规范化补充信息",
  reconciling: "正在复核 Event 事实",
  finalizing: "正在组织回答",
};

const completedStageLabels: Record<AskProgress["stage"], string> = {
  comparing: "已比较 Event 数据库",
  researching: "已获取并规范化补充信息",
  reconciling: "已复核 Event 事实",
  finalizing: "已组织回答",
};

function ThinkingTrace({ active, progress }: { active: boolean; progress: AskProgress }) {
  if (active) {
    return <div className="ask-thinking" role="status"><span className="ask-thinking__pulse" aria-hidden="true" /><div><strong>{stageLabels[progress.stage]}</strong><span>{progress.elapsed_seconds} 秒</span><ol>{progress.stages.map((stage) => <li key={stage}>{stage === progress.stage ? stageLabels[stage] : completedStageLabels[stage]}</li>)}</ol></div></div>;
  }
  return <details className="ask-thinking ask-thinking--complete"><summary>已思考 {progress.elapsed_seconds} 秒</summary><ol>{progress.stages.map((stage) => <li key={stage}>{completedStageLabels[stage]}</li>)}</ol></details>;
}

function HistoricalExchange({ item }: { item: AskHistoryItem }) {
  return <div className="ask-exchange">
    <div className="ask-message ask-message--user"><p>{item.question}</p></div>
    <div className="ask-message ask-message--assistant">
      <details className="ask-thinking ask-thinking--complete"><summary>已思考 {item.thinking_seconds ?? 0} 秒</summary><ol>{item.process_stages.map((stage) => <li key={stage}>{completedStageLabels[stage]}</li>)}</ol></details>
      {item.answer ? <p className="ask-message__answer">{item.answer}</p> : <p className="ask-message__error">{item.status === "failed" ? "该轮提问未能完成。" : "该轮仍在处理中。"}</p>}
    </div>
  </div>;
}

export function AskPanel({ selectedEvents, onClearSelection, workspace = false }: AskPanelProps) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const [grokEnabled, setGrokEnabled] = useState(false);
  const [askId, setAskId] = useState<string | null>(null);
  const [submittedQuestion, setSubmittedQuestion] = useState<string | null>(null);
  const [submittedEvents, setSubmittedEvents] = useState<{ id: string; title: string }[] | null>(null);
  const refreshedAskId = useRef<string | null>(null);
  const conversationRef = useRef<HTMLDivElement>(null);
  const create = useMutation({ mutationFn: ({ eventIds, text, useGrok }: { eventIds: string[]; text: string; useGrok: boolean }) => createAsk(eventIds, text, useGrok) });
  const ask = useQuery({
    queryKey: askId === null ? ["ask", "idle"] : askQueryKey(askId),
    queryFn: () => fetchAsk(askId!),
    enabled: askId !== null,
    refetchInterval: (query) => query.state.data?.status === "pending" || query.state.data?.status === "running" ? 1_500 : false,
  });
  const selectedEventIds = selectedEvents.map((event) => event.id);
  const history = useQuery({
    queryKey: [...askHistoryQueryKey, "conversation", ...selectedEventIds],
    queryFn: () => fetchAskHistory(100),
    enabled: workspace && selectedEventIds.length > 0,
  });
  const historicalExchanges = useMemo(() => {
    if (selectedEventIds.length === 0) return [];
    const selected = new Set(selectedEventIds);
    return (history.data?.items ?? [])
      .filter((item) => item.ask_id !== askId && item.event_ids.some((eventId) => selected.has(eventId)))
      .slice()
      .reverse();
  }, [askId, history.data?.items, selectedEventIds]);

  useEffect(() => {
    const conversation = conversationRef.current;
    if (conversation !== null) conversation.scrollTop = conversation.scrollHeight;
  }, [ask.data?.progress.elapsed_seconds, ask.data?.status, historicalExchanges.length, submittedQuestion]);

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
  const displayEvents = isActive ? submittedEvents ?? selectedEvents : selectedEvents;
  const hasConversation = historicalExchanges.length > 0 || submittedQuestion !== null;

  if (displayEvents.length === 0 && !workspace) return null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = question.trim();
    if (text.length === 0 || create.isPending || isActive || selectedEvents.length === 0) return;

    create.mutate({ eventIds: selectedEvents.map((eventToAsk) => eventToAsk.id), text, useGrok: grokEnabled }, {
      onSuccess: (accepted) => {
        setAskId(accepted.ask_id);
        setSubmittedQuestion(text);
        setSubmittedEvents(selectedEvents);
        setQuestion("");
        setGrokEnabled(false);
        refreshedAskId.current = null;
        void queryClient.invalidateQueries({ queryKey: askHistoryQueryKey });
      },
    });
  }

  const completed = ask.data?.status === "completed" ? ask.data.result : null;
  const failed = ask.data?.status === "failed" ? ask.data.error : null;

  return (
    <section className={`ask-panel${workspace ? " ask-panel--workspace" : ""}${selectedEvents.length > 0 ? " ask-panel--contextual" : ""}${hasConversation ? " ask-panel--conversation" : ""}`} aria-label={workspace ? "Ask 对话" : undefined} aria-labelledby={workspace ? undefined : "ask-heading"}>
      {!workspace && <p className="editorial-label">ASK</p>}
      {!workspace && <h2 id="ask-heading">询问观澜</h2>}
      <div className="ask-conversation" aria-live="polite" ref={conversationRef}>
        {workspace && history.isPending && selectedEvents.length > 0 && <p className="ask-conversation__loading">正在载入相关历史对话…</p>}
        {historicalExchanges.map((item) => <HistoricalExchange item={item} key={item.ask_id} />)}
        {submittedQuestion !== null && <div className="ask-exchange ask-exchange--current">
          <div className="ask-message ask-message--user"><p>{submittedQuestion}</p></div>
          <div className="ask-message ask-message--assistant">
            {ask.data?.progress && <ThinkingTrace active={isActive} progress={ask.data.progress} />}
            {ask.isError && <><p className="ask-message__error">无法检查该 Ask，请稍后重试。</p><button className="text-button" onClick={() => { void ask.refetch(); }} type="button">重试状态检查</button></>}
            {failed !== null && <p className="ask-message__error" role="alert">{failed.message}</p>}
            {completed !== null && <><p className="ask-message__answer">{completed.answer}</p><p className="ask-answer-boundary">分析回答，不作为 Evidence。</p>{completed.updated_event_ids.length > 0 && <p className="ask-updated" role="status">事件信息已补充，NOW 与事件详情已刷新。</p>}</>}
          </div>
        </div>}
      </div>
      <div className="ask-composer">
        <p className="ask-selection">{displayEvents.length === 0 ? "请选择至少一个 Event" : `${displayEvents.length} 个 Event：${displayEvents.map((eventToAsk) => eventToAsk.title).join(" · ")}.`} {!isActive && displayEvents.length > 0 && <button className="text-button" onClick={onClearSelection} type="button">清除选择</button>}</p>
        <form className="ask-form" onSubmit={submit}>
          <label className="visually-hidden" htmlFor="ask-question">你的问题</label>
          <textarea disabled={create.isPending || isActive} id="ask-question" maxLength={2000} onChange={(event) => setQuestion(event.target.value)} placeholder="你想了解什么？" required value={question} />
          <label className="ask-grok-toggle"><span>增强搜索</span><select aria-label="Grok 增强搜索" disabled={create.isPending || isActive} onChange={(event) => setGrokEnabled(event.target.value === "on")} value={grokEnabled ? "on" : "off"}><option value="off">关闭</option><option value="on">开启 Grok</option></select></label>
          {(question.trim().length > 0 || create.isPending || isActive) && <button aria-busy={create.isPending || isActive} aria-label={isActive ? "处理中" : "发送问题"} className={`auth-submit ask-send-button${create.isPending || isActive ? " ask-send-button--busy" : ""}`} disabled={create.isPending || isActive || question.trim().length === 0 || selectedEvents.length === 0} title={isActive ? "处理中" : "发送问题"} type="submit"><SendIcon className="action-icon" /></button>}
        </form>
        {create.isError && <p className="auth-error" role="alert">无法开始 Ask，请稍后重试。</p>}
      </div>
    </section>
  );
}
