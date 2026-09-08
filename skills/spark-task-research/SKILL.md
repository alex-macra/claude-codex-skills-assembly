---
name: spark-task-research
description: "Repository-grounded research for DGX Spark and Qwen3-Coder-Next implementation work: verify files, symbols, versions, dependencies, commands, and risks before task planning. Use for DGX Spark task research, Qwen task research, or preparing repository evidence for implementation packets. Task decomposition belongs to spark-task-planning."
license: MIT
metadata:
  display-name: "Spark Task Research"
  version: "1.1"
  platforms: "claude-code codex"
  tags: "research qwen spark task preparation"
---

# Spark task research

Build a factual repository brief that lets a planner remove design ambiguity before work reaches Qwen3-Coder-Next. Research only; do not implement or decompose the work into task packets.

Here, Spark means an NVIDIA DGX Spark coding-agent target. Apache Spark data-processing work belongs to the normal research and backend skills unless the request also explicitly targets Qwen3-Coder-Next execution.

## Research contract

1. Read repository instructions and the named epic, issue, or task source.
2. Record the repository, branch, current commit, relevant package versions, and applicable local rules.
3. Verify every referenced file, symbol, behavior, dependency, and command against the pinned commit object plus any explicitly separated relevant local state. Read complete relevant files rather than treating snippets or search results as implementation truth.
4. Label each important item as `existing`, `proposed`, `missing`, or `conflicting`. Never present a proposed symbol as existing code.
5. Find reusable patterns and nearby tests. Cite repository evidence as `path:line`.
6. Identify public contracts, data changes, compatibility requirements, error semantics, security boundaries, concurrency constraints, and rollout concerns that the planner must resolve.
7. Confirm the cheapest focused checks and broader verification commands actually available in the repository. Do not invent commands merely to complete the brief.
8. Use external sources only for facts the checkout cannot answer. Record the applicable version and source.

## Committed evidence boundary

- Record the full commit object ID for `HEAD`, plus the branch, upstream ref, and worktree status for every repository inspected. Verify ref equality instead of inferring it from branch names.
- Assign each repository a short identity and one execution working directory. Cite committed source as `repo-id:path:line @ <full-commit-object-id>` so cross-repository paths cannot be confused.
- Pin implementation claims to committed bytes. On a dirty tree, use the pinned commit for source facts and list overlapping working-tree paths separately; never let uncommitted or ignored content silently prove committed product behavior.
- Inspect pinned objects with pinned-object commands. When a claim also depends on a mutable branch or remote-tracking ref, first assert that ref resolves to the expected full commit, then inspect that commit instead of substituting checkout `HEAD`.
- When a task genuinely depends on a local artifact, record its absolute owning repository, producer revision, tracking state, SHA-256, byte length, embedded paths, and consumer. A file that exists but points at a missing store is not a usable input.
- For cross-repository work, record one full commit per repository and identify exactly one writable repository for the packet. If completion needs separate branches or delivery histories, research separate task units and an integration checkpoint.

## Executability pass

Before returning `READY` or `NO_CHANGE_NEEDED`:

- Resolve every existing path and symbol at the pinned commit, not only in the current working copy.
- Classify each command as a current-state preflight or reproducer, a post-change focused check, a broader gate, or live/artifact proof. State the working directory and what a zero or non-zero result means.
- Run safe read-only preflights when available. Confirm required tools, inputs, permissions, and repository instructions exist without installing, editing, or contacting an external service.
- Bind build and validation tools to their declared lockfile, install source, or container identity. An ambient `node_modules`, global binary, cache, or credential is evidence only when its provenance and required scope are recorded.
- For CI plans, inspect each job as an isolated clean checkout. One job's setup, artifact, environment variable, or credential does not exist in another job unless the workflow transfers it explicitly.
- Inspect output identity, locks, idempotency, retry, partial-failure recovery, and collision behavior. A command that cannot be safely rerun after failure is not executable until the packet fixes or explicitly resolves that contract.
- Map every acceptance claim to evidence. An internal consistency check cannot substitute for required cross-repository, runtime, artifact, browser, or served-response proof.
- Make negative claims over the complete decision domain. A narrow line slice, one guessed filename, or one current import site cannot prove repository-wide absence.

Stop when a material product or architecture decision is unresolved. Report the decision and evidence instead of choosing for the planner.

End with exactly one readiness outcome:

- `READY` - repository evidence is sufficient for planning and the requested change is not already proven complete.
- `BLOCKED_BY_SPEC` - a missing decision, unusable input, unsafe retry, contradiction, or unverifiable load-bearing claim prevents a deterministic packet. Name the owner, exact output needed, and a read-only reproducer when one exists.
- `NO_CHANGE_NEEDED` - every acceptance case is already satisfied at the pinned commits. Record and run the complete proof set; partial, internal-only, or stale proof is `BLOCKED_BY_SPEC`.

## Output

Produce a concise brief with:

- Research question and desired end state
- Repository baseline and applicable instructions
- Verified starting point, including existing, proposed, missing, and conflicting items
- Reusable prior art with `path:line` evidence
- Contracts, invariants, and compatibility constraints
- Dependencies and ordering constraints
- Verification commands and what each proves
- Open decisions, discrepancies, and risks
- Readiness outcome and planner handoff

If planning was also requested and the evidence is sufficient, hand the brief to `spark-task-planning`. Keep facts and assumptions visibly separate.
