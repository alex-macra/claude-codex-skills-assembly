---
name: spark-task-research
description: "Repository-grounded research for DGX Spark and Qwen3-Coder-Next implementation work: verify files, symbols, versions, dependencies, commands, and risks before task planning. Use for DGX Spark task research, Qwen task research, or preparing repository evidence for implementation packets. Task decomposition belongs to spark-task-planning."
license: MIT
metadata:
  display-name: "Spark Task Research"
  version: "1.0"
  platforms: "claude-code codex"
  tags: "research qwen spark task preparation"
---

# Spark task research

Build a factual repository brief that lets a planner remove design ambiguity before work reaches Qwen3-Coder-Next. Research only; do not implement or decompose the work into task packets.

Here, Spark means an NVIDIA DGX Spark coding-agent target. Apache Spark data-processing work belongs to the normal research and backend skills unless the request also explicitly targets Qwen3-Coder-Next execution.

## Research contract

1. Read repository instructions and the named epic, issue, or task source.
2. Record the repository, branch, current commit, relevant package versions, and applicable local rules.
3. Verify every referenced file, symbol, behavior, dependency, and command against the current checkout. Read complete relevant files rather than treating snippets or search results as implementation truth.
4. Label each important item as `existing`, `proposed`, `missing`, or `conflicting`. Never present a proposed symbol as existing code.
5. Find reusable patterns and nearby tests. Cite repository evidence as `path:line`.
6. Identify public contracts, data changes, compatibility requirements, error semantics, security boundaries, concurrency constraints, and rollout concerns that the planner must resolve.
7. Confirm the cheapest focused checks and broader verification commands actually available in the repository. Do not invent commands merely to complete the brief.
8. Use external sources only for facts the checkout cannot answer. Record the applicable version and source.

Stop when a material product or architecture decision is unresolved. Report the decision and evidence instead of choosing for the planner.

End with exactly one readiness outcome:

- `READY` - repository evidence is sufficient for planning and the requested change is not already proven complete.
- `BLOCKED_BY_SPEC` - a missing decision, contradiction, or unverifiable load-bearing claim prevents a deterministic packet.
- `NO_CHANGE_NEEDED` - repository evidence already satisfies the requested outcome; name the commands or observations that prove it.

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
