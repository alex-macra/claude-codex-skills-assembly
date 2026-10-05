# Contributing to AI Skills Assembly

Contribute reusable, cross-project guidance. Keep organization, account, product, repository, customer, and identity-specific material in a private catalog. Contributions use this repository's MIT License; no CLA is required.

## Skills

- Put each skill at `skills/<name>/SKILL.md`; match its lowercase hyphenated frontmatter `name`.
- Include a trigger-focused `description` of at most 250 characters and `license: MIT`.
- Register it in `catalog.json` and its intended profiles; add routing rules plus at least three positive fixtures and matching negatives when activation applies.
- Keep optional detail in `references/*.md`, linked directly from `SKILL.md` and exactly one level deep.

## Frontmatter policy

Skills stick to agentskills.io-standard frontmatter fields so they stay portable to Codex. The library deliberately does not adopt `when_to_use` (it duplicates the description's listing cost on Claude and is invisible on Codex), `disable-model-invocation` (it severs suggestion-hook activation, since the model performs the invocation), or skill-registered hooks. Revisit only with measured need.

## Tool grants and names

- Scope every `allowed-tools` grant, such as `Bash(git status:*)`. A bare `Bash` or `Bash(*)` fails validation.
- Name a skill or agent in prose only when `catalog.json` declares it. The validator checks each backticked hyphenated name followed by the word skill or agent.

## Size caps

`scripts/validate.py` enforces these hard caps. A line is one element of `splitlines()`; bytes are the UTF-8 file size. Never raise a cap in a change that cuts content.

| Files | Lines | Bytes |
|---|---|---|
| `skills/*/SKILL.md` | 60 | 5,000 |
| `SKILL.md` of `delivery-loop` and `fast-pr-workflow`, a list that may only shrink | 80 | 7,000 |
| `skills/*/references/*.md`, one level deep | 80 | 6,000 |
| `agents/*.md`, preloading at most 3 skills | 20 | 2,000 |
| `templates/CLAUDE.md` and `templates/AGENTS.md`, kept identical | 40 | 4,000 |
| `templates/output-styles/*.md` | 20 | 1,500 |
| Any other `.md` | 80 | none |

Skill and agent descriptions are at most 250 characters. The default-profile listing (names plus descriptions) warns above 2,500 characters and fails above 3,000.

## Output styles

- Put each output style at `templates/output-styles/<name>.md`, lowercase hyphenated, matching its catalog key.
- Set `keep-coding-instructions: true` in its frontmatter unless the style deliberately drops Claude Code's software-engineering behavior.
- Register it in `catalog.json` under `outputStyles` and in its intended profiles. Installing a style links the file; it still needs a person to select it.

## Public boundary

- Exclude private names, paths, domains, architecture, commands, tickets, and incident narratives.
- Exclude secrets, credentials, customer data, health information, and proprietary source.
- Exclude generated caches, local settings, and installed symlinks.

## Validate

Run `python3 scripts/validate.py` before opening a pull request and report skipped checks or limitations. Add `--denylist FILE`, or set `AI_SKILLS_DENYLIST`, to scan tracked text and paths for private terms kept in an uncommitted list outside the repository.
