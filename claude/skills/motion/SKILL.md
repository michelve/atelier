---
name: motion
description: Add, review or set up UI motion in any web project, following that project's own motion tokens, helpers and reduced-motion strategy. Use for transitions, keyframes, micro-interactions, entrances, panel morphs, hover and press feedback, scroll or pointer effects, tweened numbers, charts that draw in, loading and live-state loops, and reduced-motion handling, in plain CSS, CSS modules, Tailwind, motion/react (Framer Motion), GSAP, WAAPI, React Three Fiber or canvas. Also for "audit the animations", "why is this janky", "respect reduced motion", "set up motion tokens". NOT for rendered video, turntables or 3D asset animation (use refkit).
argument-hint: "<what to animate> | audit [path] | init"
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(node *motion-scan.mjs*), Bash(git diff *), Bash(git status *), Bash(git ls-files *), Bash(npm run lint*), Bash(npm run build*), Bash(npm test*), Bash(npm run test*), Bash(npm run typecheck*), Bash(npm run type-check*), Bash(pnpm lint*), Bash(pnpm build*), Bash(pnpm test*), Bash(pnpm run lint*), Bash(pnpm run build*), Bash(pnpm run test*), Bash(pnpm run typecheck*), Bash(yarn lint*), Bash(yarn build*), Bash(yarn test*), Bash(yarn typecheck*), Bash(bun run lint*), Bash(bun run build*), Bash(bun test*), Bash(bun run test*), Bash(bun run typecheck*)
---

# Motion

Motion explains a change: where something came from, what just changed, what is selected, that something is live. This skill adds motion the way the current project already does it, audits existing motion, or sets up a motion system where there is none.

Request: $ARGUMENTS

- Starts with `audit`: run **Audit** on the paths after it. With no path, audit the files git reports as changed.
- Is `init`: run **Init**.
- Anything else, including an automatic invocation with no arguments: run **Guide**. The task comes from the request or from the conversation.

## Step 0: profile the project (every mode)

1. From the project root, run the scanner with the Bash tool:
   `node "${CLAUDE_SKILL_DIR}/scripts/motion-scan.mjs" profile`
   It reports:
   - the stack, package manager and scripts
   - motion tokens (found by value, not name) and their reduced-motion overrides
   - local choreography timings
   - JS timing constants
   - the reduced-motion strategy
   - helper modules, motion docs, lint rules and test mocks
2. Read what it points to before writing anything:
   - the Motion sections and motion docs it lists
   - the token file
   - the helper module
   - one existing component that animates, as a style reference
3. Say in one line what you found. For example: "Tokens `--dur-1..3` / `--ease-*` in src/styles/tokens.css, 0ms under reduced motion; local `--t-*` timings; helpers in src/lib/anim.ts; Stylelint checks durations; docs/motion.md has an effects library."

**Precedence:** the project's docs first, then the project's code conventions, then this skill. When the project disagrees with this skill, follow the project. Only say so when it affects accessibility (reduced motion, flashing, pause controls).

**No motion system found:** in Guide, use the defaults from [templates/motion-tokens.css](templates/motion-tokens.css) and [reference/principles.md](reference/principles.md), and mention `/motion init` once at the end. Don't scaffold anything uninvited.

## Guide: add or change motion

1. **Purpose.** In one sentence, say what the motion explains. If it explains nothing, don't add it. Ambient motion (idle float, hero loop, particles) is fine only when the project's art direction asks for it, and only with the guards in [principles.md](reference/principles.md#ambient-motion).
2. **Reuse before inventing.** Look first at the project's own effects library or catalogue in its motion doc, then at [reference/recipes.md](reference/recipes.md). Only invent a new effect when nothing fits, and say why.
3. **Timing from tokens.**
   - Hover, press, focus and colour changes use the fastest token. Entrances and state changes use the middle one. Deliberate reveals use the slow one.
   - A choreographed piece (a morph or a sequence) may use its own timings. Name them as custom properties at the top of its root rule, using the project's prefix (default `--t-*`). Never write a raw `ms` value in a transition, a delay or a `calc()`.
   - Exits run 20–30% faster than entrances. Content leaves first and arrives last.
4. **Keep the framework out of every frame.**
   - Pointer lean, scroll, scrubbing, counters and morph measurements write CSS custom properties through a ref (`el.style.setProperty("--x", v)`), or use motion values or `gsap.quickTo`.
   - Never set framework state in `pointermove`, `scroll`, `requestAnimationFrame` or `useFrame`.
5. **JS animation goes through the project's helper** (`tween`, `countUp`, `useCountUp`, `animateValue`, …). Return its cancel function from the effect, or from the in-view callback.
   - If the project has no helper and you need one, copy [templates/anim.ts](templates/anim.ts) into its lib folder and say so.
   - JS timings come from the CSS tokens (`cssMs("--dur-2")`), not new constants.
6. **Animate cheap properties:** `transform`, `translate`, `scale`, `rotate`, `opacity`, `clip-path`, masks, and registered custom properties that drive these.
   - Not `width`, `height`, `top`, `left`, `margin`, `padding` or `font-size`. Use `clip-path`, a transform, or FLIP instead.
   - Don't use `transition: all`.
   - Don't mix `transform` with the separate `translate`/`scale` properties on one element unless on purpose, and make sure the CSS minifier doesn't merge them.
7. **Reduced motion, the project's way.** [stacks.md](reference/stacks.md#reduced-motion-strategies) covers each strategy.
   - Token durations drop to zero on their own. Custom timings don't: give them the component's own reduce block, or put the whole entrance inside `@media (prefers-reduced-motion: no-preference)` so reduce shows the end state.
   - Delays are custom timings too.
   - In JS, use the project's check. Tweens should jump straight to the end value.
   - Reduce means no movement, not no feedback. Keep fades and colour changes; drop travel, scaling, parallax and loops. Always show the final state.
   - Anything that waits for `animationend` or `transitionend` must still complete under reduce. Call the completion path directly, or use a near-zero duration and the lint exception comment the project already uses.
8. **Place it where the project puts motion.** Use the component's own CSS file or module, the project's cascade layer and naming (BEM, modules), and Tailwind theme tokens rather than arbitrary values.
   - A component that sets `transition` replaces the whole shorthand, so it must repeat the hover and press transitions of any shared component it restyles.
   - Name keyframes after the component (`care-plan-pop`), because global stylesheets share one namespace.
9. **Accessibility.**
   - Morphs and panels move focus in when they open, and back to the trigger when they close.
   - Status changes are announced in text (`aria-live`), not only through motion.
   - Charts that draw in get `role="img"` and a one-sentence label.
   - Nothing flashes more than 3 times a second.
   - Anything that moves on its own for more than 5s has a pause control.
10. **Verify.**
    - Run the lint, build, typecheck and test scripts from the profile, using the package manager from its lockfile.
    - If the profile's Tests line shows a `matchMedia` mock, add a reduced-motion test: the final value shows at once, and completion callbacks still run.
    - Run `node "${CLAUDE_SKILL_DIR}/scripts/motion-scan.mjs" audit <changed files>` and fix what applies.
    - Don't drive a browser. Give the user a short checklist:
      - desktop width, and about 390px
      - reduced motion on and off (DevTools → Rendering → Emulate CSS prefers-reduced-motion)
      - keyboard only
      - loops pause when scrolled away or when the tab is hidden
      - the Animations panel at 10% speed, to judge the easing
    - If the project has a motion doc, add the new effect to it: its effects library or catalogue, using the doc's own table format.

## Audit

1. Run Step 0. Then run `node "${CLAUDE_SKILL_DIR}/scripts/motion-scan.mjs" audit [paths]`. It lists at most 20 hits per rule; narrow the path, or add `--all`.
2. **Check each hit in context.** Read the lines around it, and for CSS hits the component's JS too. For example, a pointer-lean transition whose handler returns early under reduced motion is handled. Drop false positives, and say how many you dropped.
3. Add the checks the scanner can't make, from [reference/audit.md](reference/audit.md#checks-by-eye).
4. Items the project's motion doc already lists as known exceptions or known gaps go in a short **Known** group, one line each. They are not new findings.
5. **Report.**
   - Group the findings into **Must fix**, **Should fix** and **Consider**.
   - Write each one as `file:line — rule — fix`, and make the fix concrete (which token, which block, which recipe).
   - End with one line: the number of findings in each group, and which one to fix first and why.

**Don't edit anything** until the user says which findings to fix.

## Init

Run Step 0 first.

**The project has no motion system.** Propose a short plan, show it, and ask before writing anything:
- **Tokens** in the project's own format:
  - CSS custom properties in its token file ([templates/motion-tokens.css](templates/motion-tokens.css))
  - Tailwind v4 `@theme` ([templates/motion-theme.css](templates/motion-theme.css))
  - for projects that animate only through motion or GSAP, a presets module ([stacks.md](reference/stacks.md))
  - If the project already has part of a scheme (say, easing tokens only), extend it with the same prefix.
- **A reduced-motion baseline:** a token override by default. Add a page-wide safety rule only if there is a lot of legacy animation.
- **Helpers, only when the project animates in JS:** [anim.ts](templates/anim.ts), plus [use-in-view.ts](templates/use-in-view.ts) and [use-reduced-motion.ts](templates/use-reduced-motion.ts) for React.
- **`docs/motion.md`** from [templates/motion-doc.md](templates/motion-doc.md), filled in with what already exists.
- **A four-bullet Motion section** for `CLAUDE.md` (or `AGENTS.md`) that points to the doc.
- **If the project uses Stylelint:** the duration rule from [stacks.md](reference/stacks.md#lint).

**The project already has a system.** Write or refresh `docs/motion.md` from the template, without changing code:
- tokens as they stand
- effects in use, catalogued from the code
- the reduced-motion strategy and its gaps (run the audit over the whole source)
- known exceptions
End with a summary of what changed in the doc.

## Reference

- [reference/principles.md](reference/principles.md): what motion is for, timing scale, easing meaning, choreography, ambient guards, performance, accessibility.
- [reference/recipes.md](reference/recipes.md): the effects library, with code. It covers:
  - entrances, morphs, reveals, pointer effects, one-shot replays, draws, tweens and odometers
  - `@starting-style`, View Transitions, scroll-driven animations, `linear()` springs, FLIP and disclosures
- [reference/stacks.md](reference/stacks.md): reduced-motion strategies, rules for each library, test mocks, lint.
- [reference/audit.md](reference/audit.md): every scanner rule with its fix and common false positives, plus the checks by eye.
- [templates/](templates/): tokens, a Tailwind theme, animation helpers, React hooks, and the motion doc outline.
