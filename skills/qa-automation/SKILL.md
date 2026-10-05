---
name: qa-automation
description: "Write, run and fix automated tests: unit, integration, and browser, CLI or HTTP end-to-end; fixtures, mocks, coverage, flakes. Use when adding or debugging tests (pytest, vitest, jest, Playwright, Cypress) or E2E journeys."
license: MIT
metadata:
  display-name: "QA Automation"
  version: "2.0"
  platforms: "claude-code codex"
  tags: "testing unit integration e2e fixtures"
---

# QA automation

## Levels

- **Unit:** pure functions or single classes; no I/O, network or clock.
- **Integration:** real dependencies (db, fs, queue) in process; mocks only at the system boundary.
- **E2E:** the running app through its public interface (browser, HTTP, CLI); load `references/e2e.md`.

Pick the cheapest level that catches the bug: mostly unit, a thin integration layer, a few critical E2E flows. An inverted pyramid means slow, flaky CI.

## Writing a test

- Arrange, act, assert; one concept per test. A name needing "and" is two tests.
- Test behavior through the public API, not private state or call counts.
- Name scenario and outcome: `returns_400_when_email_missing`.
- Small explicit data in the test body beats `beforeEach` magic.

## Mocks versus reals

- Database, filesystem, in-process queue: real (in-memory db, tmp dir). Mocked persistence hides schema drift; default to a real in-memory db.
- HTTP to your own service: real, in a harness. Third party: stub at the boundary (`nock`, `respx`, `MSW`) with responses recorded once.
- Time: inject a clock or fake timers; never `sleep` to wait. Randomness: seed it.

## Stack notes

- **Vitest and Jest:** `vitest run` or `jest --ci` in CI; reset mocks in `afterEach`; commit snapshots and never `--update-snapshot` reflexively; with React, query by role or label, not test-ids.
- **Pytest:** `-x --ff` while developing; explicit fixture scope, `autouse` only for global setup; `parametrize` over loops; `pytest-randomly` for order bugs, `pytest-xdist` for parallelism.
- **HTTP integration:** real app on an ephemeral port; per-test rollback transaction or fresh schema; one `login()` helper.

## Coverage

A percentage alone is meaningless: `expect(result).toBeDefined()` covers a line and proves nothing. Cover preconditions, branches, error paths and edge values (empty, max, negative, unicode). Delete unreachable defensive code instead of testing it.

## Flakes

A flaky test is broken; fix it, never retry it green. Causes: timing, shared state, real network, ordering, time-of-day logic. Reproduce with shuffled order and repeats (`--repeat-each=20`). A genuinely racy codebase means the test found a real bug.

## Adding tests to existing code

1. For a bug, write the failing reproduction first.
2. Run only that test until green, then the surrounding suite, then the full suite once before committing.
3. Tests pass deterministically on a clean checkout with only documented env vars.
4. Never `--ignore` a failing test to merge; fix or delete it.

Not a launch-and-look pass: that is `see-it-live`.
