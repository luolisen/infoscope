import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { components } from "../../api/schema";
import { fetchOnboarding, OnboardingError, onboardingQueryKey, updateOnboarding } from "../../api/onboarding";
import { sessionQueryKey } from "../../api/session";

type Step = "scope" | "markets" | "focus";
type Answers = components["schemas"]["OnboardingSelection"];

const emptyAnswers: Answers = { scope_ids: [], investment_market_ids: [], focus_ids: [] };

function toggle<T>(items: T[], item: T) { return items.includes(item) ? items.filter((value) => value !== item) : [...items, item]; }

type OnboardingPendingProps = {
  editExisting?: boolean;
  onComplete?: () => void;
};

export function OnboardingPending({ editExisting = false, onComplete }: OnboardingPendingProps = {}) {
  const queryClient = useQueryClient();
  const onboarding = useQuery({ queryKey: onboardingQueryKey, queryFn: fetchOnboarding });
  const [answers, setAnswers] = useState<Answers | null>(null);
  const [step, setStep] = useState<Step>("scope");
  const [localError, setLocalError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: updateOnboarding,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: sessionQueryKey }),
        queryClient.invalidateQueries({ queryKey: onboardingQueryKey }),
      ]);
      onComplete?.();
    },
  });

  if (onboarding.isPending) return <main className="state-page"><p>Preparing your view…</p></main>;
  if (onboarding.isError || !onboarding.data) return <main className="state-page"><p role="alert">We could not load onboarding.</p></main>;

  const data = onboarding.data;
  const currentAnswers = answers ?? (editExisting ? data.answers : emptyAnswers);
  const requiresMarkets = currentAnswers.scope_ids.includes("investment");
  const options = step === "scope" ? data.scope_options : step === "markets" ? data.investment_market_options : data.focus_options;
  const selected = step === "scope" ? currentAnswers.scope_ids : step === "markets" ? currentAnswers.investment_market_ids : currentAnswers.focus_ids;
  const label = step === "scope" ? "01 / SCOPE" : step === "markets" ? "01.1 / 投资市场" : "02 / FOCUS";
  const title = step === "scope" ? "哪些内容进入你的视野？" : step === "markets" ? "你更关注？" : "什么内容应该更容易浮上来？";
  const hint = step === "scope" ? "后续更新将提供自定义SCOPE" : step === "focus" ? "后续更新将提供自定义FOCUS" : null;

  function choose(id: typeof options[number]["id"]) {
    setLocalError(null);
    if (step === "scope") setAnswers({ ...currentAnswers, scope_ids: toggle(currentAnswers.scope_ids, id as components["schemas"]["ScopeId"]), investment_market_ids: id === "investment" || currentAnswers.scope_ids.includes("investment") ? currentAnswers.investment_market_ids : [] });
    else if (step === "markets") setAnswers({ ...currentAnswers, investment_market_ids: toggle(currentAnswers.investment_market_ids, id as components["schemas"]["InvestmentMarketId"]) });
    else setAnswers({ ...currentAnswers, focus_ids: toggle(currentAnswers.focus_ids, id as components["schemas"]["FocusId"]) });
  }
  function next() {
    if (selected.length === 0) { setLocalError("Select at least one option to continue."); return; }
    if (step === "scope") { setStep(requiresMarkets ? "markets" : "focus"); return; }
    if (step === "markets") { setStep("focus"); return; }
    save.mutate({ ...currentAnswers, investment_market_ids: requiresMarkets ? currentAnswers.investment_market_ids : [] });
  }
  const apiError = save.error instanceof OnboardingError && save.error.code === "INVALID_ONBOARDING_SELECTION" ? "Your selections need updating. Please review them." : save.isError ? "We could not save your view. Please try again." : null;
  return <main className="onboarding-page"><section className="onboarding-step" key={step}>
    <p className="editorial-label">{label}</p><h1>{title}</h1>
    <div className="choice-list">{options.map((option) => <button aria-pressed={selected.includes(option.id as never)} key={option.id} onClick={() => choose(option.id)} type="button"><span>{option.label}</span><span aria-hidden="true">{selected.includes(option.id as never) ? "×" : "+"}</span></button>)}</div>
    {(localError || apiError) && <p className="auth-error" role="alert">{localError ?? apiError}</p>}
    <div className="onboarding-actions">{step !== "scope" && <button className="text-button" onClick={() => setStep(step === "focus" ? (requiresMarkets ? "markets" : "scope") : "scope")} type="button">Back</button>}<button className="auth-submit" disabled={save.isPending} onClick={next} type="button">{step === "focus" ? (editExisting ? "Save view" : "Establish view") : "Continue"}</button></div>
    {hint && <p className="onboarding-hint">{hint}</p>}
  </section></main>;
}
