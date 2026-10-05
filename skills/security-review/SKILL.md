---
name: security-review
description: "Security review of a codebase or authorized target: OWASP Top 10, secrets, auth, input validation, supply chain, CI hygiene. Use for a security audit, CVE check, pentest-style review, hardening, or secret leaks."
license: MIT
metadata:
  display-name: "Security Review"
  version: "2.0"
  platforms: "claude-code codex"
  tags: "security owasp audit hardening secrets supply-chain"
---

# Security review

For a general break-it pass use `adversarial-review`. Per-category commands and grep patterns live in `references/checklist.md`; work from it during the pass.

## Authorization gate

Codebase review (static) needs no gate; read freely. Before testing any running system, confirm in writing:

- The system is ours, a CTF, a personal lab, or a paid engagement.
- The in-scope targets and the explicitly out-of-scope ones.
- The allowed methods (DoS, social engineering and supply-chain attacks are out by default) and the disclosure rules.

If any of it is unclear, stop and ask before sending packets.

## Decision rules

- String-built SQL, shell commands or templates fed user input are blockers: parameterized queries and argument arrays only.
- Validate every external input at the boundary with a schema; type coercion is not validation.
- Authorization is per request: every endpoint asks whether this user may touch this resource.
- Secrets live in env or a secret store, scoped per environment, never echoed to logs. Hardcoded fallbacks and committed `.env` files are blockers. Rotate on departure or runner replacement.
- Library crypto only; never `Math.random()` for tokens, never fast hashes for passwords.
- Wildcard CORS with credentials is a blocker. Verify JWT signature, `alg` and `exp` before reading claims.
- Server-side fetches of user URLs are SSRF until proven otherwise: allowlist hosts, block metadata and link-local ranges.
- JSON is safe to deserialize; any richer format on untrusted input needs scrutiny.
- Untrusted LLM input is data, not instructions: delimit it, and verify model output before acting on it.
- CI: workflow `permissions:` least-privilege, third-party actions pinned to a commit SHA, base images pinned by digest, lockfile committed, no publishing from a laptop and no secrets exposed to fork builds.

## Categories

Codebase: secrets, input validation, injection, authn and authz, XSS and encoding, CSRF and CORS, SSRF, crypto, deserialization, supply chain, logging, LLM-specific.

Live target (authorized only): recon, auth surface, web app, API, infra.

## Findings

Severity: Blocker (correctness, security, data loss) / Should-fix (compounding design debt) / Nit.

Each finding: severity with reasoning, location (`path:line` or URL and parameter), reproduction (steps or a curl one-liner), attacker impact, and the specific fix.

## Out of bounds

Unauthorized targets, mass exploitation or destructive payloads, detection evasion for malicious use, compromising third-party packages, and DoS testing without written approval.
