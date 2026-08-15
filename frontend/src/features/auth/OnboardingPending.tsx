type OnboardingPendingProps = {
  username: string | undefined;
};

export function OnboardingPending({ username }: OnboardingPendingProps) {
  return (
    <main className="state-page">
      <p className="editorial-label">01 / SCOPE</p>
      <h1>Your view is nearly ready.</h1>
      <p>{username ?? "Your account"} is authenticated. Continue with SCOPE when the onboarding service is available.</p>
    </main>
  );
}
