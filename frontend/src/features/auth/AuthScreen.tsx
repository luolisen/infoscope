import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AuthenticationError, login, register } from "../../api/auth";
import { sessionQueryKey } from "../../api/session";

type AuthMode = "login" | "register";

function messageFor(error: unknown) {
  if (error instanceof AuthenticationError) {
    if (error.code === "USERNAME_TAKEN") {
      return "用户名已被使用。";
    }

    if (error.code === "INVALID_CREDENTIALS") {
      return "用户名或密码不正确。";
    }
  }

  return "无法完成请求，请稍后重试。";
}

export function AuthScreen() {
  const [mode, setMode] = useState<AuthMode>("login");
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (credentials: { username: string; password: string }) =>
      mode === "login" ? login(credentials) : register(credentials),
    onSuccess: (session) => queryClient.setQueryData(sessionQueryKey, session),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    mutation.mutate({
      username: String(formData.get("username") ?? ""),
      password: String(formData.get("password") ?? ""),
    });
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
        <p className="editorial-label">INFOSCOPE / ACCESS</p>
        <h1 id="auth-title">建立你的视野。</h1>
        <p className="auth-panel__intro">登录后继续使用你的个人情报界面。</p>

        <div className="auth-mode" role="group" aria-label="Authentication mode">
          <button type="button" aria-pressed={mode === "login"} onClick={() => setMode("login")}>登录</button>
          <button type="button" aria-pressed={mode === "register"} onClick={() => setMode("register")}>注册</button>
        </div>

        <form className="auth-form" onSubmit={submit}>
          <label>
            <span>用户名</span>
            <input autoComplete="username" name="username" required />
          </label>
          <label>
            <span>密码</span>
            <input autoComplete={mode === "login" ? "current-password" : "new-password"} name="password" required type="password" />
          </label>
          {mutation.isError && <p className="auth-error" role="alert">{messageFor(mutation.error)}</p>}
          <button aria-label={mode === "login" ? "提交登录" : "提交注册"} className="auth-submit" disabled={mutation.isPending} type="submit">
            {mutation.isPending ? "处理中…" : mode === "login" ? "登录" : "创建账户"}
          </button>
        </form>
      </section>
    </main>
  );
}
