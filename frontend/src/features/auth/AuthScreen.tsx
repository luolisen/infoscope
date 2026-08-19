import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { accessLocal, AuthenticationError } from "../../api/auth";
import { sessionQueryKey } from "../../api/session";

function messageFor(error: unknown) {
  if (error instanceof AuthenticationError) {
    if (error.code === "LOCAL_USER_CONFLICT") {
      return "本地身份正在初始化，请稍后重试。";
    }
  }

  return "无法完成请求，请稍后重试。";
}

type AuthScreenProps = {
  onDemoContinue?: () => void;
};

export function AuthScreen({ onDemoContinue }: AuthScreenProps = {}) {
  const [localError, setLocalError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: accessLocal,
    onSuccess: (session) => queryClient.setQueryData(sessionQueryKey, session),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const displayName = String(formData.get("display_name") ?? "").trim();
    if (!displayName) {
      setLocalError("请告诉我们如何称呼您。");
      return;
    }
    setLocalError(null);
    if (onDemoContinue) {
      onDemoContinue();
      return;
    }
    mutation.mutate({ display_name: displayName });
  }

  return (
    <main className="auth-page">
      <div className="auth-preview" aria-hidden="true">
        <header className="auth-preview__topbar"><span>IS</span><span>搜索&nbsp;&nbsp;⌘K</span></header>
        <div className="auth-preview__body">
          <aside><span>NOW</span><span>BRIEF</span><span>ARCHIVE</span><hr /><span>SCOPE</span><span>SETTINGS</span></aside>
          <section><p>NOW / SYSTEM</p><h1>看见事件，<br />而不是信息流。</h1><div /><div /></section>
        </div>
      </div>

      <section className="auth-panel" aria-labelledby="auth-title">
        <p className="editorial-label">INFOSCOPE / WELCOME</p>
        <h1 id="auth-title">我们怎么称呼您？</h1>
        <p className="auth-panel__intro">先留下一个称呼，再建立属于你的视野。</p>

        <form className="auth-form" onSubmit={submit}>
          <label>
            <span>称呼</span>
            <input autoComplete="name" autoFocus name="display_name" required />
          </label>
          {(localError || mutation.isError) && <p className="auth-error" role="alert">{localError ?? messageFor(mutation.error)}</p>}
          <button aria-label="继续建立视野" className="auth-submit" disabled={mutation.isPending} type="submit">
            {mutation.isPending ? "正在准备…" : "继续"}
          </button>
        </form>
      </section>
    </main>
  );
}
