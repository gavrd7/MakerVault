# Security Policy

## Reporting a vulnerability

Please **do not open a public GitHub issue** for a suspected security vulnerability.

Use GitHub's private vulnerability reporting feature for this repository where available. This keeps the report private while the issue is assessed and fixed.

If the private reporting option is not available, contact the maintainer privately rather than publishing exploit details, credentials, sensitive logs or deployment information in an issue.

When reporting a vulnerability, include:

- the affected MakerVault version or commit;
- the component or feature involved;
- clear reproduction steps;
- the expected and observed security impact;
- any relevant logs or screenshots, with secrets and personal information removed;
- whether the issue affects a default installation or requires unusual configuration.

Please give the maintainer reasonable time to investigate and prepare a fix before public disclosure.

## Supported versions

Security fixes are primarily targeted at the current stable release and the current `main` branch.

Older releases may require upgrading to receive a fix.

## Scope

Useful security reports include issues involving:

- authentication or account takeover;
- authorization or cross-user data access;
- private-file access or encryption handling;
- backup/recovery exposure;
- credential or secret disclosure;
- server-side request handling;
- privilege escalation;
- unsafe default deployment behaviour.

Reports about third-party services, printer firmware or products outside MakerVault itself should normally be reported to the responsible vendor unless MakerVault introduces or amplifies the issue.

## Public reports

Once a fix is available, a public advisory or release note may be created when appropriate. Sensitive details may be limited until users have had time to update.
