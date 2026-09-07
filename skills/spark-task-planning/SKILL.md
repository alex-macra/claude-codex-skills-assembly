---
name: spark-task-planning
description: "Turn approved architecture and repository evidence into dependency-ordered implementation packets for Qwen, Qwen3-Coder-Next, or DGX Spark. Use only when the request explicitly targets one of those execution contexts; generic task packets and Apache Spark planning do not belong here."
license: MIT
metadata:
  display-name: "Spark Task Planning"
  version: "1.2"
  platforms: "claude-code codex"
  tags: "planning qwen spark task packets"
---

# Spark task planning

Convert an approved design and repository-grounded evidence into work packets that Qwen3-Coder-Next can execute without making a new product or architecture decision.

Here, Spark means an NVIDIA DGX Spark coding-agent target, not Apache Spark data processing. Use this skill only when the request explicitly targets Qwen, Qwen3-Coder-Next, or DGX Spark.

Read [references/qwen-task-packet.md](references/qwen-task-packet.md) before drafting packets and use its schema.

After drafting, run `scripts/validate-packets.py <packet.md>`. An explicit file must contain at least one visible packet and must be a regular non-symlink Markdown file no larger than 8 MiB. The validator accepts the standalone, embedded-ledger, and legacy-compatible bold-label renderings; requires the 15 fields in order and exactly one readiness outcome; and checks the execution-critical detail contract: nonblank revalidation trigger, repository inventory, absolute execution root, worktree/collision state, exact read and write sets, at least two line-separated change steps, four-case acceptance matrix, line-separated numbered verification with expected result and proof claim, and a revision-bound handoff. It also refuses branch-only evidence for `READY` or `NO_CHANGE_NEEDED`. A `BLOCKED_BY_SPEC` packet with no selected repository instead records `Not applicable - <reason>` for its immutable evidence and execution root. These are structural gates; the planning pass must still prove that every path, symbol, command, and acceptance claim is semantically correct.

Every task-packet field in that schema is mandatory. If a field truly does not apply, keep its heading or embedded label and write `Not applicable - <reason>` instead of omitting it.

## Inputs

Require enough evidence to distinguish existing code from proposed work:

- Desired end state and approved architecture decisions
- Repository, base commit or ref, applicable instructions, and relevant versions
- Verified files, symbols, patterns, and test commands
- Public contracts, invariants, non-goals, compatibility rules, and risk constraints
- Prerequisites and known ordering constraints

If load-bearing repository facts are missing, use `spark-task-research` before planning. If a shared epic-level product or architecture choice remains unresolved, stop the batch and name it. If the choice affects only one lane, emit a `BLOCKED_BY_SPEC` packet for that lane and its descendants while continuing independent lanes. Never hide the choice inside an implementation step.

Perform assumption closure before decomposition. Enumerate decisions an implementer could encounter and classify each one as fixed by the architecture contract, safe for the worker to decide locally, or unresolved. Any unresolved consequential decision makes the affected packet and its dependent descendants `BLOCKED_BY_SPEC`; a shared epic-level decision may block the full batch.

Packet readiness is execution truth at the pinned evidence snapshot. It is independent of a roadmap, issue, or canonical ledger status; show both when they differ instead of copying one into the other.

Pin existing-code claims to committed evidence. Cite them as `repo-id:path:line @ <full-commit-object-id>`. Keep dirty or ignored artifacts explicit, identity-bound inputs rather than allowing them to redefine the implementation base.

Use exactly one readiness outcome per packet. A batch may contain mixed outcomes; summarize their counts without replacing packet-level truth. A blocker applies to its packet and dependency descendants, not to independent lanes:

- `READY` - this packet is decision-complete and executable at its stated starting point.
- `BLOCKED_BY_SPEC` - this packet has a missing or conflicting required decision, repository fact, or predecessor output; emit the blocker rather than speculative steps.
- `NO_CHANGE_NEEDED` - verified evidence shows this packet's desired end state already holds, so it should not enter implementation.

## Decomposition rules

- One packet delivers one observable behavior or one mechanically coherent change.
- One executable packet has one writable repository, one branch lineage, and one delivery history. Split cross-repository writes into separately identified packets and join them at an integration checkpoint.
- Size by unresolved decisions, not file count. A broad mechanical edit can be one task; a small change with two design choices is not ready.
- Put stable architecture decisions in the epic dossier, then repeat only the decisions a packet needs to remain self-contained.
- State decision authority explicitly. The worker may choose local control flow, private naming, test fixtures, and trivial compile repairs within the contract. The worker must escalate public APIs, architecture or ownership, persistence or schemas, dependencies, security policy, error semantics, compatibility behavior, and scope expansion unless the packet fixes them.
- Mark every referenced file, symbol, schema, endpoint, or fixture as existing or proposed.
- State exact inputs, outputs, error behavior, compatibility expectations, security constraints, and concurrency semantics when they apply.
- Name the credential's actual capabilities, preferred minimum scope, provenance, and injection point when a command needs authentication. Credential capability never grants permission to mutate. Require a dedicated read-only credential when the packet's threat model fixes that boundary, and never print credential values in a command, log, packet, or handoff.
- Enumerate every local or ignored file the worker may consume. Record its canonical absolute path, regular-file type, byte length, and lowercase SHA-256, or state explicitly that the manifest is empty. For a directory or compound input, define a deterministic member manifest and list every consumed member; never treat a directory path alone as an input identity.
- Give acceptance cases that can fail for a real defect. Never let the implementation worker weaken them to obtain a green result.
- Name exact verification commands already confirmed by research, ordered from focused to broader checks.
- Separate commands that prove the current blocker from commands that become runnable only after implementation. Every command names its working directory, expected result, and proof claim.
- Use immutable object IDs inside evidence commands. If readiness depends on a mutable ref, add an exact ref-to-object assertion before using the ref; never use checkout `HEAD` as a substitute for the packet's pinned base.
- Run `READY` and `NO_CHANGE_NEEDED` proof in a clean dedicated checkout or state an exact clean tracked-and-untracked precondition. A dirty shared checkout cannot prove which bytes passed.
- For predecessor artifacts, name the producer task and revision plus the expected digest, byte length, schema, and destination. The consumer verifies identity before use.
- State worktree overlap, output collision, idempotency, retry, and partial-failure recovery. Never instruct the worker to delete or overwrite retained evidence merely to rerun a task.
- When one packet block is the serialized output, pin its baseline digest, define the exact byte range and digest algorithm, abort on mismatch, and restart from a newly researched baseline rather than merging concurrent prose edits.
- For CI work, specify every job as a fresh checkout with its own tool setup, artifact downloads, environment, and proof. Do not let one child packet inherit another job's filesystem or credentials implicitly.
- Use explicit prerequisite task IDs and an execution DAG. Parallel lanes need stable interfaces and non-overlapping write scopes.
- Add an integration checkpoint after a group of parallel or contract-coupled tasks, and at least every three to six packets in a long epic.
- Include escalation conditions for repository drift, missing APIs, schema changes, new dependencies, or any decision not settled by the packet.
- Give each packet to a fresh execution context with only its self-contained packet and required repository instructions. Keep the epic dossier as the single planning authority instead of asking the worker to reconstruct decisions from the planning transcript.

## Interpretability standard

- Write concrete nouns, paths, symbols, values, units, cardinalities, and expected results. Avoid `as needed`, `appropriate`, `relevant tests`, `fix issues`, `use the existing pattern`, or pronouns whose referent is outside the packet.
- Separate current fact, required change, and proof. A missing file is evidence for a blocker, not an implementation target unless the packet explicitly proposes it.
- Make absence checks exhaustive for the stated scope. Query the complete scripts object, ref namespace, dependency set, or source tree instead of presenting a selected excerpt as proof of absence.
- Give every step an input, action, and observable output. Identify the exact read set before the exact write set.
- Acceptance is a case matrix: normal behavior, boundary or failure behavior, compatibility behavior, and security or concurrency behavior when applicable. Each case names its proof command or observation.
- `READY` requires usable inputs, a collision-safe execution path, and runnable preflight. `NO_CHANGE_NEEDED` requires complete proof for every acceptance case. Otherwise use `BLOCKED_BY_SPEC` and name the exact decision or evidence that unlocks replanning.
- Render the reference schema as standalone headings or as the documented embedded-ledger fields. The 15 labels and their order are identical; only the Markdown representation changes.

## Output

Produce:

1. One epic dossier containing the shared architecture contract and explicit non-goals.
2. One execution DAG showing prerequisites, parallel-safe lanes, and integration checkpoints.
3. One self-contained Markdown packet per task using the reference template. Only `READY` packets are executable.
4. A final coverage check mapping every required outcome to at least one task and acceptance case, plus packet-outcome counts and blocked dependency descendants.

Packets are inputs to `delivery-loop`. They do not authorize implementation, dependency installation, commits, pushes, or pull requests by themselves.
