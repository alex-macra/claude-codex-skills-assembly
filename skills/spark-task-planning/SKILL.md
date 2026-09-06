---
name: spark-task-planning
description: "Turn approved architecture and repository evidence into dependency-ordered implementation packets for Qwen, Qwen3-Coder-Next, or DGX Spark. Use only when the request explicitly targets one of those execution contexts; generic task packets and Apache Spark planning do not belong here."
license: MIT
metadata:
  display-name: "Spark Task Planning"
  version: "1.0"
  platforms: "claude-code codex"
  tags: "planning qwen spark task packets"
---

# Spark task planning

Convert an approved design and repository-grounded evidence into work packets that Qwen3-Coder-Next can execute without making a new product or architecture decision.

Here, Spark means an NVIDIA DGX Spark coding-agent target, not Apache Spark data processing. Use this skill only when the request explicitly targets Qwen, Qwen3-Coder-Next, or DGX Spark.

Read [references/qwen-task-packet.md](references/qwen-task-packet.md) before drafting packets and use its schema.

Every top-level task-packet section in that schema is mandatory. If a section truly does not apply, keep its heading and write `Not applicable - <reason>` instead of omitting it.

## Inputs

Require enough evidence to distinguish existing code from proposed work:

- Desired end state and approved architecture decisions
- Repository, base commit or ref, applicable instructions, and relevant versions
- Verified files, symbols, patterns, and test commands
- Public contracts, invariants, non-goals, compatibility rules, and risk constraints
- Prerequisites and known ordering constraints

If load-bearing repository facts are missing, use `spark-task-research` before planning. If a product or architecture choice remains unresolved, stop and name it rather than hiding it inside a task.

Perform assumption closure before decomposition. Enumerate decisions an implementer could encounter and classify each one as fixed by the architecture contract, safe for the worker to decide locally, or unresolved. Any unresolved consequential decision makes the result `BLOCKED_BY_SPEC`.

Use exactly one readiness outcome for the planning result:

- `READY` - every emitted packet is decision-complete and executable at its stated starting point.
- `BLOCKED_BY_SPEC` - at least one required decision or repository fact is missing or conflicting; emit blockers, not a speculative executable packet.
- `NO_CHANGE_NEEDED` - verified evidence shows the desired end state already holds, so no implementation packet should be queued.

## Decomposition rules

- One packet delivers one observable behavior or one mechanically coherent change.
- Size by unresolved decisions, not file count. A broad mechanical edit can be one task; a small change with two design choices is not ready.
- Put stable architecture decisions in the epic dossier, then repeat only the decisions a packet needs to remain self-contained.
- State decision authority explicitly. The worker may choose local control flow, private naming, test fixtures, and trivial compile repairs within the contract. The worker must escalate public APIs, architecture or ownership, persistence or schemas, dependencies, security policy, error semantics, compatibility behavior, and scope expansion unless the packet fixes them.
- Mark every referenced file, symbol, schema, endpoint, or fixture as existing or proposed.
- State exact inputs, outputs, error behavior, compatibility expectations, security constraints, and concurrency semantics when they apply.
- Give acceptance cases that can fail for a real defect. Never let the implementation worker weaken them to obtain a green result.
- Name exact verification commands already confirmed by research, ordered from focused to broader checks.
- Use explicit prerequisite task IDs and an execution DAG. Parallel lanes need stable interfaces and non-overlapping write scopes.
- Add an integration checkpoint after a group of parallel or contract-coupled tasks, and at least every three to six packets in a long epic.
- Include escalation conditions for repository drift, missing APIs, schema changes, new dependencies, or any decision not settled by the packet.
- Give each packet to a fresh execution context with only its self-contained packet and required repository instructions. Keep the epic dossier as the single planning authority instead of asking the worker to reconstruct decisions from the planning transcript.

## Output

Produce:

1. One epic dossier containing the shared architecture contract and explicit non-goals.
2. One execution DAG showing prerequisites, parallel-safe lanes, and integration checkpoints.
3. One self-contained Markdown packet per task using the reference template. Only `READY` packets are executable.
4. A final coverage check mapping every required outcome to at least one task and acceptance case.

Packets are inputs to `delivery-loop`. They do not authorize implementation, dependency installation, commits, pushes, or pull requests by themselves.
