# AI Skills Assembly for Claude Code and Codex

Reusable agent skills, deterministic activation, safety hooks, and installers for Claude Code and OpenAI Codex, with an agentskills.io-compatible skill surface.

Version 1 supports Python 3.10 or newer on Linux and macOS.

## Catalog

| Name | Kind | Job |
|---|---|---|
| `delivery-loop` | skill | One approved packet becomes a verified, reviewed, smoked change with one open PR |
| `fast-pr-workflow` | skill | The only commit, push, PR create, PR update, and merge procedure, with a scoped tool grant |
| `orchestrator` | skill | Supervise delivery work: a loop in this session, a whole session, or other sessions |
| `task-research` | skill | Evidence brief before a plan or packet: prior art first, then docs, facts vs assumptions |
| `qa-automation` | skill | Write, run, and fix tests: unit, integration, and browser, CLI, and HTTP end-to-end |
| `see-it-live` | skill | Run the app, prove the specific change is visible, smoke the critical path |
| `architect-review` | skill | Design and code review: boundaries, coupling, naming, reuse, comment hygiene |
| `security-review` | skill | OWASP, secrets, auth, input validation, supply chain, CI token and action pinning |
| `adversarial-review` | skill | Independent pass that tries to break the change and ends in a failing input and a verdict |
| `web-dev` | skill | TypeScript and Python web rules with frontend, backend, deploy and CI, and accessibility references |
| `reviewer` | agent | Read-only review that preloads the three review skills |
| `orchestrator` | agent | Supervisor role for a dedicated session or a background subagent |

## Install

```bash
python3 install.py user
python3 install.py project /absolute/path/to/repo
```

Both commands install the `default` profile on the Claude Code, OpenAI Codex, and Agents surfaces. Repeat `--surface` with `claude`, `codex`, or `agents` to limit surfaces. Use `--dry-run` to preview and `--uninstall` to remove managed entries. Installs are idempotent, preflight all targets, refuse unmanaged conflicts, back up modified settings and text files as numbered `.bak` files, and track ownership in `.ai-skills-managed.json`.

`--extra-skills DIR` (repeatable) also links every subdirectory of `DIR` that holds a `SKILL.md`, for private skills kept outside any catalog. Each passes the catalog checks first: name matches its directory, description of at most 250 characters, the size caps, no unscoped `Bash` grant, no clash with a catalog skill, no symlinked skill directory, and `DIR` outside every catalog root. Extra skills get no routing rule, are never installed by default, and a later run without the flag removes them.

## Optional integrations

Activation, usage logging, protected-branch command checks, and global rule templates are opt-in through `python3 install.py user --hooks --global-rules`.

The usage hook records `ts`, invoked `skill`, and hook-provided `cwd` as JSONL in `~/.ai-skills/skill-usage.jsonl` with user-only permissions. Override the path with `AI_SKILLS_USAGE_LOG`. Uninstall leaves existing log data intact.

Install the protected-branch Git hook separately with `python3 install.py merge-guard /absolute/path/to/repo`. Command and Git hooks are advisory defense-in-depth, not security boundaries. Enforce protected branches remotely with required checks, reviews, and credentials that cannot bypass them.

## Compose catalogs

`catalog.json` is the canonical inventory. Paths are relative to the catalog that declares them; repeat `--catalog` and `--profile` to add a private overlay:

```bash
python3 install.py project /absolute/path/to/repo \
  --catalog /absolute/path/to/claude-codex-skills-assembly/catalog.json \
  --catalog /absolute/path/to/overlay/catalog.json \
  --profile default \
  --profile team-project
```

Selected profiles are the complete desired set on selected surfaces. Pass every profile that should remain active. Plain `--uninstall` also removes installer-managed hooks and global rules without requiring their opt-in flags.

The activation hook emits matching skill names from `routing/skill-rules.json`, fails open on malformed input, and never injects skill bodies. Keywords of four characters or fewer match whole words only. A prompt trigger can use `excludePatterns` to suppress its keyword and intent matches while leaving file-path activation available.

## Delivery

`task-research` produces verified repository evidence, and the task owner turns approved architecture and that evidence into dependency-ordered Markdown packets. `delivery-loop` takes one approved packet through eight phases: validate, implement, test and build, fix and retest, architecture and adversarial review, final smoke, commit, push, and open the PR, then verify the remote handoff. A request to run the loop authorizes its shipping bundle (task branch, commit, push, one PR) unless the request narrows it; merge, deploy, release, and tags stay separate gates. `fast-pr-workflow` owns the commit and PR mechanics.

An optional task tracker is an executable at `~/.config/ai-skills/task-tracker`. When it exists and the packet names a task ID, the loop reports claims, checkpoints, and the review through it; otherwise the handoff says `tracker: none`. The contract is in `skills/delivery-loop/references/tracker.md`.

For several packets, a milestone, or a long loop, `orchestrator` conducts builders and keeps one rolling PR per repository. It can also watch a whole session or other sessions; it never edits the watched tree and never merges.

Delivery runs can keep optional resumable state under `.codex/delivery-state/`. The executable `scripts/delivery-state.py` helper creates and verifies private ignored state without following symlinks or accepting hard links; state adds no phases and grants no authority. The nonblocking browser helper coordinates test execution through a stable system directory lease, with one suite and one worker by default.

## Agent portability

Agent files install on the Claude Code surface only (`surfaces.agents` in `catalog.json`), where Claude Code preloads the skills an agent declares. Codex takes roles inline: a Codex dispatcher names the `SKILL.md` files each subagent must read completely before acting.

## Output styles

The `default` profile installs the `Terse` output style file to the Claude surface's `output-styles/` directory. Installing it does not turn it on - a style only changes Claude Code's behavior once selected with `/config` (Output style) or by setting `"outputStyle": "Terse"` in a Claude Code settings file. A style change takes effect after `/clear` or a new session.

## Contribute

See [CONTRIBUTING.md](CONTRIBUTING.md) for the public boundary, the size caps, and the validation command, [SECURITY.md](SECURITY.md) for private reporting, and [LICENSE](LICENSE) for the MIT License. `python3 scripts/validate.py --denylist FILE` (or `AI_SKILLS_DENYLIST`) also scans tracked text and paths for private terms kept in an uncommitted list outside the repository.
