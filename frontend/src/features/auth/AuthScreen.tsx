import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AuthenticationError, login, register } from "../../api/auth";
import { sessionQueryKey } from "../../api/session";

type AuthMode = "login" | "register";

function messageFor(error: unknown) {
  if (error instanceof AuthenticationError) {
    if (error.code === "USERNAME_TAKEN") {
      return "This username is already in use.";
    }

    if (error.code === "INVALID_CREDENTIALS") {
      return "Username or password is incorrect.";
    }
  }

  return "We could not complete that request. Please try again.";
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

  const actionLabel = mode === "login" ? "Log in" : "Create account";

  return (
    <main className="auth-page">
      <div className="auth-preview" aria-hidden="true">
        <header className="auth-preview__topbar"><span>IS</span><span>Search&nbsp;&nbsp;⌘K</span></header>
        <div className="auth-preview__body">
          <aside><span>NOW</span><span>BRIEF</span><span>ARCHIVE</span><hr /><span>SCOPE</span><span>SETTINGS</span></aside>
          <section><p>NOW / SYSTEM</p><h1>See the event,<br />not the feed.</h1><div /><div /></section>
        </div>
      </div>

      <section className="auth-panel" aria-labelledby="auth-title">
        <p className="editorial-label">INFOSCOPE / ACCESS</p>
        <h1 id="auth-title">Establish your view.</h1>
        <p className="auth-panel__intro">Sign in to continue with your personal intelligence interface.</p>

        <div className="auth-mode" role="group" aria-label="Authentication mode">
          <button type="button" aria-pressed={mode === "login"} onClick={() => setMode("login")}>Log in</button>
          <button type="button" aria-pressed={mode === "register"} onClick={() => setMode("register")}>Register</button>
        </div>

        <form className="auth-form" onSubmit={submit}>
          <label>
            <span>Username</span>
            <input autoComplete="username" name="username" required />
          </label>
          <label>
            <span>Password</span>
            <input autoComplete={mode === "login" ? "current-password" : "new-password"} name="password" required type="password" />
          </label>
          {mutation.isError && <p className="auth-error" role="alert">{messageFor(mutation.error)}</p>}
          <button aria-label={`Submit ${actionLabel.toLowerCase()}`} className="auth-submit" disabled={mutation.isPending} type="submit">
            {mutation.isPending ? "Working…" : actionLabel}
          </button>
        </form>
      </section>
    </main>
  );
}
