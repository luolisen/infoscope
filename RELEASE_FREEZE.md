# Release Feature Freeze

Status: **ACTIVE**  
Effective: 2026-08-19 (Asia/Shanghai)  
Scope: `SCOUT-Infoscope/infoscope` and every change targeting `main`

The submitted release is feature-complete. New product development is prohibited until Alan
explicitly lifts this freeze in a separately reviewed governance change.

## Allowed changes

Only these change classes may target `main`:

1. A release-blocking correctness fix that prevents the submitted Demo from starting or completing
   its frozen route.
2. A security or secret-removal fix.
3. A regression test for already-frozen behavior.
4. Submission, recovery, or operator documentation that does not expand product behavior.

## Prohibited changes

- New features, routes, pages, sources, providers, models, workflows, user-visible capabilities, or
  hardware behavior.
- Product scope expansion disguised as a refactor or fix.
- New database migrations or changes to OpenAPI, MQTT Schema, or frozen contracts.
- Dependency upgrades except a reviewed security remediation.
- Direct pushes, force pushes, branch deletion, or bypassing a failed required check on `main`.

## Required PR evidence

Every PR must:

- carry the `release-approved` label applied by Alan;
- use a `fix:`, `docs:`, `test:`, `chore(release):`, or `chore(security):` title;
- contain no `feat:` commit;
- explain the release blocker, smallest possible diff, regression proof, and rollback;
- pass `Release freeze gate`, including the complete `./scripts/check.sh` suite.

Changes under `backend/src/` or `frontend/src/` additionally require `release-critical-fix` or
`release-security`. Contract and migration paths remain blocked while the freeze is active.

The automated gate is necessary but not sufficient: a passing check never authorizes a merge by
itself. Human approval and the frozen-scope review remain mandatory.
