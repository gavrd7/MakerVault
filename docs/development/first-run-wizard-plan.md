# First-run administrator setup wizard — implementation plan

> Draft scope only. This document tracks the planned feature; the wizard is not implemented yet.

## Goal

Allow an operator to create the initial MakerVault administrator from a mobile-friendly browser interface without requiring `python manage.py createsuperuser`. Preserve CLI setup as an alternative.

## Proposed setup

1. On a fresh installation, show a first-run screen instead of an inaccessible sign-in page.
2. Provide a one-time, short-lived, cryptographically random **setup token** through a local server/Compose command. Do not expose the token in unauthenticated HTTP responses, application logs, or the browser by default.
3. Operator enters token to unlock admin creation; rate-limit token verification and account creation.
4. Create a single superuser with username, email and strong password. Reuse Django password validators and CSRF defenses; use atomic transactions to prevent races.
5. Optionally review timezone, currency, and measurement preferences **only when these are actually configurable without rewriting operator-defined environment configuration**.
6. Mark setup finished and redirect to login. Never permit unauthenticated re-entry after any superuser exists. CLI-created superusers must also suppress this wizard.

## Security and compatibility

- Fail closed when setup token is missing, invalid, expired, or already redeemed.
- Re-check the absence of superusers server-side at the point of creation; don't rely on UI visibility.
- Bind the initial setup flow to a deliberately invoked local CLI token issuance action. No predictable token, default password, or public first-visitor-claims-admin behavior.
- Do not weaken Allauth, MFA, OIDC, login/session, or password-reset protections.
- Ensure proxy headers, HTTPS, cookie and CSRF settings remain consistent.
- Never overwrite `.env`, secrets, storage paths or operator-provided configuration.
- Existing upgrades and installations with a superuser must behave exactly as before.
- Include tests for invalid/reused/expired tokens, concurrent requests, disabled setup after CLI superuser creation, and phone-sized layout.

## Acceptance criteria

- Fresh Docker install can create the first admin in the GUI once the operator has obtained the one-time setup token locally.
- Normal CLI superuser setup remains supported.
- Setup cannot be re-entered after the initial superuser is present.
- The wizard renders and works on mobile devices.
- No changes to data ownership, storage keys, database passwords or environment settings.
- All existing CI, backend security tests, frontend checks and Docker build checks pass.

## Dependencies

Keep implementation independent of PR #78 (account settings and roles), then reconcile its settings/navigation when ready. Do not merge this draft as documentation-only functionality.
