# Security review checklist

Per-category detail for both modes. Decision rules, severity ladder and reporting format live in `SKILL.md`.

## Codebase review

### Secrets and credentials
- Grep `password`, `secret`, `api_key`, `token`, `BEGIN PRIVATE KEY`, cloud access-key prefixes; `git log --all -p` for historical leaks.
- `.env*` and config files are never committed; check `.gitignore`. Logger redaction covers every key the app handles.
- CI: use the platform secret store, scope secrets to environments, keep production secrets away from fork builds.

### Input validation
- Validate body, query, header, path, upload, queue message and env var at the boundary; reject unknown fields.
- Uploads: sniff content type, enforce size limits, store outside the web root, never execute.

### Injection
- SQL and NoSQL (`$where`, operator injection): parameterize. Command: no `shell=True` with user input.
- LDAP, XPath, XML, regex (ReDoS), templates (SSTI): never `eval` user input.
- Prompt injection: wrap untrusted content in delimited tags and instruct the model to treat it as data.

### Authn and authz
- Passwords: `argon2id`, `scrypt` or `bcrypt` (cost 12 or more); never `md5`, `sha1`, `sha256`.
- Sessions: `httpOnly`, `secure`, `sameSite`, rotated on privilege change, expired on logout.
- JWT: reject `none`; verify signature before claims; check `exp`, `iss`, `aud`.
- OAuth: validate `state` and `redirect_uri`; PKCE for public clients.
- Lockout and rate limits per account, not just per IP.

### XSS, CSRF, CORS
- Render text as text; `innerHTML`, `dangerouslySetInnerHTML`, `v-html` only with sanitized content.
- CSP with explicit sources and no `'unsafe-inline'` scripts; `nosniff`, `frame-ancestors` or `X-Frame-Options`, `Referrer-Policy`.
- Mutations need SameSite plus a CSRF token or a custom header. CORS uses an explicit origin allowlist.

### SSRF
- Allowlist hosts; block `localhost`, `127.0.0.0/8`, `169.254.169.254`, `::1`, `0.0.0.0`, link-local.
- Resolve DNS once and use the IP; re-check every redirect hop.

### Crypto and deserialization
- `libsodium`, `cryptography`, `node:crypto`; AES-GCM or ChaCha20-Poly1305, never ECB; CSPRNG tokens; TLS 1.2+ with HSTS.
- `pickle.loads`, `yaml.load` without `SafeLoader`, `Marshal` and Java native serialization on untrusted input mean RCE.

### Supply chain and CI
- `npm audit`, `pip-audit`, `cargo audit` or `osv-scanner` on every PR; lockfile committed and reviewed; watch typosquats and `postinstall` hooks.
- Pin third-party actions to a commit SHA, set `permissions:` per workflow and job, pin base images by digest, never `latest`.
- Containers run as non-root with a `HEALTHCHECK`. Build artifacts come from CI, never a laptop.

### Logging
- Never log passwords, tokens, full bodies, PII or payment data. Do log auth events, admin actions, access denials and integrity changes; alert on failure spikes.

### LLM-specific
- De-identify sensitive data before any model call; keys stay in env, out of client code.
- Never `eval` model output or let it shape SQL without parameterization.

## Live target testing (authorized only)

- **Recon:** DNS and subdomain enumeration, light port scan first, fingerprinting, robots, sitemap, public buckets.
- **Auth surface:** enumeration via timing or messages, brute-force protection, token entropy and fixation, reset-token predictability and host-header takeover.
- **Web app:** map every input and try SQLi, XSS, SSRF, IDOR, traversal, command injection; interceptors and `sqlmap` or `ffuf` with rate limits; no noisy fuzzing of production without approval.
- **API:** enumerate endpoints, find missing auth on internal routes, JWT and mass-assignment flaws, try every endpoint as user A with user B's IDs.
- **Infra:** `testssl.sh` or `sslyze` for weak ciphers, expired certs and missing HSTS; cloud metadata via SSRF; listable or writable buckets.
