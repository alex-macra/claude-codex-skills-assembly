# AI Skills Assembly for Claude Code and Codex

Reusable agent skills, deterministic activation, safety hooks, and installers for Claude Code and OpenAI Codex, with an agentskills.io-compatible skill surface.

Version 1 supports Python 3.10 or newer on Linux and macOS.

## Install

```bash
python3 install.py user
python3 install.py project /absolute/path/to/repo
```

Both commands install the `default` profile on the Claude Code, OpenAI Codex, and Agents surfaces. Repeat `--surface` with `claude`, `codex`, or `agents` to limit surfaces. Use `--dry-run` to preview and `--uninstall` to remove managed entries.

Installs are idempotent, preflight all targets, refuse unmanaged conflicts, back up modified settings and text files as numbered `.bak` files, and track ownership in `.ai-skills-managed.json`.

## Optional integrations

Activation, usage logging, protected-branch command checks, and global rule templates are opt-in:

```bash
python3 install.py user --hooks --global-rules
```

The usage hook records `ts`, invoked `skill`, and hook-provided `cwd` as JSONL in `~/.ai-skills/skill-usage.jsonl` with user-only permissions. Override the path with `AI_SKILLS_USAGE_LOG`. Uninstall leaves existing log data intact.

Install the protected-branch Git hook separately:

```bash
python3 install.py merge-guard /absolute/path/to/repo
```

Command and Git hooks are advisory defense-in-depth, not security boundaries. Enforce protected branches remotely with required checks, reviews, and credentials that cannot bypass them.

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

The activation hook emits matching skill names from `routing/skill-rules.json`, fails open on malformed input, and never injects skill bodies. A prompt trigger can use `excludePatterns` to suppress its keyword and intent matches while leaving file-path activation available.

## Agent portability

Claude Code can preload the skills declared in an agent definition. Codex dispatchers must explicitly instruct each subagent to read the required `SKILL.md` files completely before acting. The agent definitions state both behaviors instead of assuming one host's preload model applies to another.

The DGX Spark task pipeline separates repository research, task planning, implementation, and PR mechanics. `spark-task-research` produces verified repository evidence. `spark-task-planning` turns approved architecture and that evidence into dependency-ordered, Qwen-ready Markdown packets; its bounded `scripts/validate-packets.py` accepts standalone, embedded-ledger, and legacy-compatible bold-label packets and enforces the ordered field schema, one packet status, immutable revision evidence, explicit execution boundaries, canonical local-input manifests, numbered change and proof steps, a four-case acceptance matrix, and a revision-bound handoff. The skill still requires the planner to check that those paths, anchors, commands, and claims are semantically correct for every repository. `delivery-loop` validates and executes one packet through implementation, test/build, and fix/retest. `fast-pr-workflow` handles an optional authorized PR handoff after validation is green.

Delivery runs can keep optional resumable state under `.codex/delivery-state/`. The executable `scripts/delivery-state.py` helper creates and verifies private ignored state without following symlinks or accepting hard links. The state records the four delivery phases but does not add phases or grant authority. The nonblocking browser helper coordinates test execution through a stable system directory lease, with one suite and one worker by default.

## Output styles

The `default` profile installs the `Terse` output style file to the Claude surface's `output-styles/` directory. Installing it does not turn it on - a style only changes Claude Code's behavior once selected with `/config` (Output style) or by setting `"outputStyle": "Terse"` in a Claude Code settings file. A style change takes effect after `/clear` or a new session.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the public boundary and validation command, [SECURITY.md](SECURITY.md) for private reporting, and [LICENSE](LICENSE) for the MIT License.
