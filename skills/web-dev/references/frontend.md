# Frontend

TypeScript with React, Vue or Svelte. The shared type, validation and done rules live in `SKILL.md`.

## Types
- Prefer `unknown` over `any` at boundaries; narrow with guards or `zod`.
- `readonly` for data that must not mutate; `as const` for literal narrowing.
- Discriminated unions over optional-everywhere objects: `{ status: 'idle' | 'loading' | 'success' | 'error' }` beats five booleans.

## Components
- Functions, not classes, except to wrap an imperative third-party API.
- One responsibility each; a 200-line component usually splits well. Props typed as `<Component>Props`; 12 props means two components.
- No prop drilling past 2 levels: context, a store or composition.
- List `key` is a stable data id, never the index unless the list is immutable and append-only.
- Design systems: atoms are single-element primitives, molecules compose atoms for one job, organisms are page-level blocks with business meaning. Shared parts live in atoms and molecules; app compositions stay in the app.
- Theme through CSS custom properties, not hardcoded palette classes, so apps re-theme by overriding variables.

## Hooks and composables
- Effects synchronize with something external; if it is "do X on mount", ask whether an event handler fits.
- Complete dependency arrays; fix the dependency instead of silencing the lint rule.
- Logic shared by two or more components becomes `use<Thing>`.
- New code does not fetch in an effect: use the framework data layer (TanStack Query, SWR, RSC, SvelteKit `load`).

## State
- Local first; lift only when two components need it.
- Server state is not client state: use a query cache, not Redux or Zustand.
- Forms use a library (react-hook-form, vee-validate, felte).
- The URL is state: filters, tabs, pagination and modals belong there when shareable.

## Styling
- Use the project's system (Tailwind, CSS Modules, vanilla-extract, styled-components); no inline styles for anything dynamic enough to deserve a class.
- Spacing, color and radii come from tokens, never hand-tuned hex values.
- Dark mode: a `class="dark"` toggle plus a CSS-variable swap is the most portable.

## Accessibility while building
- Everything interactive is keyboard-reachable with a visible focus ring; `<button>` for actions, `<a>` for navigation, never `<div onClick>`.
- Inputs have `<label>`s; `aria-label` is a fallback. Images have `alt`, decorative ones `alt=""`. State is never color alone.
- Modals: `role="dialog"`, `aria-modal`, focus trap, Escape closes, focus returns to the trigger. Menus: `role="menu"`, `aria-haspopup`, `aria-expanded`, arrow keys.
- A full conformance pass uses `references/a11y.md`.

## Performance
- Measure first (Profiler, `performance.mark`, Lighthouse).
- Skip `useMemo` and `useCallback` for cheap work; lazy-load routes and heavy components.
- Images: correct dimensions, `loading="lazy"` below the fold, AVIF or WebP.
- Check the `dist/` diff after adding a dependency; a 300 KB date library for one `format()` call is not acceptable.

## API consumption
- One fetch wrapper owns auth, error mapping, base URL and retries.
- Components get typed data or a typed error, never a raw `Response`.
- Cancel in-flight requests on unmount (`AbortController`); optimistic updates only when undo is cheap and visible.

## Testing the UI
- Component tests query by role or label, not test-ids. Critical flows go to E2E (`qa-automation`).
- Visual regression only if the project already has a snapshot tool.
