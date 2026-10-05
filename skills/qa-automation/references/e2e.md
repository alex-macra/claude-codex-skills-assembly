# End-to-end testing

E2E tests drive the real running app through its public interface. They are slow and flaky to debug, so spend them on the few flows that must work and push everything else down a level. The 30th E2E test for one page means the pyramid is upside down.

## What belongs

- Login, core action, logout; checkout, signup, payment; a handful of flows spanning auth, data and UI state.
- Not form validation (unit), pure rendering (component), backend logic (integration), or anything cheaper at a lower level.

## Locators and waiting

- Prefer accessible queries: `getByRole('button', { name: 'Save' })`, `getByLabel`, `getByText`. They double as accessibility checks.
- Test-ids only when role or label is ambiguous; never CSS classes; name the thing instead of `.nth(3)`.
- Wait for state, not time: `expect(locator).toBeVisible()` retries, `waitForTimeout` and `cy.wait(ms)` are flakes. Prefer a visible signal over a transport one; disable animations in the test build.

## Network and data

- Real backend: a mocked API is integration testing. Stub only third parties you do not control, with `route` or `intercept`. Do not record whole journeys.
- Isolated state per test, no shared user or session. Seed through the API, not the UI; tear down or use a per-test namespace; unique identifiers (`crypto.randomUUID()`), no hardcoded emails.
- One worker and one context per test. Multi-user or multi-tab tests use separate contexts and never share cookies.

## Auth

Never script the login UI in every test. Pick by app type:

- **Cookie injection** for apps with a test-mode seed endpoint (enabled only in test mode): seed a user, add the returned session cookie to the context, then `goto`.
- **storageState plus globalSetup** for OTP or bypass-code logins: authenticate once, save to a gitignored `.auth/user.json`, reuse with `test.use({ storageState })`; stub the profile endpoint to skip a round trip.
- **Full mocking** for public apps or response-specific tests: `page.route('**/api/items*', route => route.fulfill({ status: 200, body }))` in `beforeEach`.

## CI

- Full parallelism only when runner memory fits the worker count; shard monorepos (`--shard=1/4`).
- On a shared local machine run one browser suite at a time with capped workers; never launch several browser suites concurrently unless the user asks and capacity is verified.
- `retries: 1` is reasonable, 3 masks flake. Trace on first retry only; no video of everything.

```ts
export default defineConfig({
  fullyParallel: true,
  forbidOnly: !!process.env['CI'],
  retries: process.env['CI'] ? 1 : 0,
  reporter: process.env['CI'] ? [['github'], ['list']] : 'list',
  use: { trace: 'on-first-retry' },
});
```

## Stacks

The stack is whatever the repository declares. Before concluding there is no E2E, enumerate its journey targets (build files, scripts, CI jobs, README) and run them; engine and CLI projects count.

- **Playwright:** `codegen` for scaffolding, then rewrite locators to roles; `toHaveScreenshot()` with a generous `maxDiffPixelRatio` and per-platform baselines; `test.step` for readable traces.
- **Cypress:** one assertion per chain; `cy.session()` for cached login.
- **CLI and API:** real binary, real network; spawn it and assert on stdout, stderr and exit code.

## Debugging and done

1. Reproduce locally (`--headed --debug`, `cypress open`); read the CI trace before adding logs.
2. Works locally, fails in CI is usually timing, headless rendering or data leakage; if the app is genuinely racy, fix the app.
3. Before done: three headless runs in random order with no flakes, and compare wall-clock; the cost of one more E2E is real.
