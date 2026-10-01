import { strict as assert } from "node:assert";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { after, describe, test } from "node:test";
import { fileURLToPath } from "node:url";
import { motionKind, parseCss, stripVars } from "./motion-scan.mjs";

const SCRIPT = path.join(path.dirname(fileURLToPath(import.meta.url)), "motion-scan.mjs");
const temps = [];
after(() => temps.forEach((dir) => rmSync(dir, { recursive: true, force: true })));

function project(files) {
  const root = mkdtempSync(path.join(tmpdir(), "motion-scan-"));
  temps.push(root);
  for (const [name, text] of Object.entries(files)) {
    mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
    writeFileSync(path.join(root, name), text);
  }
  return root;
}

function scan(root, ...args) {
  const result = spawnSync(process.execPath, [SCRIPT, ...args, "--json"], { cwd: root, encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

const hitsOf = (report, rule) => report.hits.filter((h) => h.rule === rule);
const linesOf = (report, rule, file) => hitsOf(report, rule).filter((h) => !file || h.file === file).map((h) => h.line);

describe("parseCss", () => {
  test("gives each declaration its line and the blocks around it", () => {
    const { decls } = parseCss(`@layer widgets {\n  .card {\n    color: red;\n    @media (hover: hover) {\n      &:hover { scale: 1.02; }\n    }\n  }\n}\n`);
    assert.deepEqual(decls.map((d) => [d.prop, d.line, d.stack.at(-1)]), [
      ["color", 3, ".card"],
      ["scale", 5, "&:hover"],
    ]);
  });

  test("ignores separators inside comments, strings, parentheses and SCSS interpolation", () => {
    const { decls } = parseCss(`.a {\n  /* b: c; } */\n  content: "x;}";\n  background: url(data:image/svg+xml;utf8,<svg/>);\n  width: #{$w};\n}\n`, { lineComments: true });
    assert.deepEqual(decls.map((d) => d.prop), ["content", "background", "width"]);
    assert.equal(decls[1].line, 4);
  });

  test("skips SCSS line comments without eating URLs", () => {
    const { decls } = parseCss(`.a {\n  // color: red;\n  background: url(http://x.test/a.png);\n}\n`, { lineComments: true });
    assert.deepEqual(decls.map((d) => d.prop), ["background"]);
  });
});

describe("motionKind", () => {
  test("classifies by value, not by name", () => {
    assert.equal(motionKind("200ms"), "duration");
    assert.equal(motionKind(".15s"), "duration");
    assert.equal(motionKind("cubic-bezier(0.22, 1, 0.36, 1)"), "easing");
    assert.equal(motionKind("linear(0, 0.5 40%, 1)"), "easing");
    assert.equal(motionKind("ease-out"), "easing");
    assert.equal(motionKind("140ms var(--ease-out)"), "shorthand");
    assert.equal(motionKind("spin 1s linear infinite"), "shorthand");
    assert.equal(motionKind("calc(170ms + var(--n) * 32ms)"), "duration");
    assert.equal(motionKind("var(--dur-1)"), "alias");
  });

  test("leaves colours, sizes and plain numbers alone", () => {
    for (const v of ["#4c080e", "0.5rem", "1", "calc(100% - 2rem)", "0 1px 2px #000", "12px 2s"]) assert.equal(motionKind(v), null, v);
  });

  test("stripVars removes nested var() calls", () => {
    assert.equal(stripVars("opacity var(--a, var(--b)) 200ms").replace(/\s+/g, " ").trim(), "opacity 200ms");
  });
});

describe("profile", () => {
  const root = project({
    "package.json": JSON.stringify({ scripts: { lint: "stylelint", build: "vite build", dev: "vite" }, dependencies: { react: "19", motion: "13" }, devDependencies: { vite: "8" } }),
    "package-lock.json": "{}",
    "src/tokens.css": `@layer tokens {\n  :root {\n    --dur-1: 200ms;\n    --ease-out: cubic-bezier(0.22, 1, 0.36, 1);\n    --t-brand: #4c080e;\n    --space-2: 0.5rem;\n  }\n  @media (prefers-reduced-motion: reduce) {\n    :root { --dur-1: 0ms; }\n  }\n}\n`,
    "src/card.css": `.card { --t-open: 460ms; --morph: cubic-bezier(0.65, 0, 0.2, 1); transition: scale var(--t-open) var(--morph); }\n`,
    "src/theme.css": `@theme {\n  --ease-snap: cubic-bezier(0.2, 0, 0, 1);\n  --animate-wiggle: wiggle 1s ease-in-out infinite;\n}\n`,
    "src/lib/anim.ts": `export function tween() {}\nexport const reducedMotion = () => false;\nexport function formatDate() {}\n`,
    "src/test/setup.ts": `window.matchMedia = (q) => ({ matches: q.includes("prefers-reduced-motion: reduce") });\n`,
    "CLAUDE.md": "# Rules\n\n## Motion\n\nUse the tokens.\n",
    "stylelint.config.mjs": `export default { rules: { "x": ["/^(transition|animation)-(duration|delay)$/"] } };\n`,
    "dist/index-DpjLFuOF.css": `:root { --dur-9: 900ms; }\n`,
    "public/assets/index-BOVmcLe6.css": `:root { --dur-8: 800ms; }\n`,
  });
  const p = scan(root, "profile");

  test("finds the stack, scripts and package manager", () => {
    assert.deepEqual(p.stack.frameworks, ["React", "Vite"]);
    assert.equal(p.stack.packageManager, "npm");
    assert.deepEqual(Object.keys(p.stack.scripts).sort(), ["build", "lint"]);
    assert.ok(p.stack.libraries.some((l) => l.startsWith("motion ")));
  });

  test("reports motion tokens only, with their reduced-motion override", () => {
    assert.deepEqual(p.tokens.map((t) => t.name).sort(), ["--animate-wiggle", "--dur-1", "--ease-out", "--ease-snap"]);
    assert.deepEqual(p.reducedMotionOverrides, ["--dur-1: 0ms"]);
    assert.ok(p.tokens.find((t) => t.name === "--ease-snap").theme);
  });

  test("groups component timings by prefix", () => {
    assert.deepEqual(p.localTimings.map((l) => l.prefix).sort(), ["--morph", "--t-*"]);
  });

  test("finds helpers, docs, lint and test support", () => {
    assert.deepEqual(p.helpers, ["src/lib/anim.ts (tween, reducedMotion)"]);
    assert.deepEqual(p.docs, ['CLAUDE.md:3 "## Motion"']);
    assert.match(p.lint[0], /checks transition\/animation/);
    assert.deepEqual(p.tests, ["src/test/setup.ts"]);
    assert.equal(p.empty, false);
  });

  test("says when a project has no motion system", () => {
    assert.equal(scan(project({ "index.html": "<p>hi</p>" }), "profile").empty, true);
  });
});

describe("audit: CSS", () => {
  const root = project({
    "tokens.css": `:root { --dur-1: 200ms; --dur-2: 600ms; --ease-out: ease-out; }\n@media (prefers-reduced-motion: reduce) { :root { --dur-1: 0ms; --dur-2: 0ms; } }\n`,
    "a.css": [
      ".slot > * { animation: card-in var(--dur-2) var(--ease-out) both; animation-delay: calc(var(--i, 0) * 70ms); }",
      ".b { transition: opacity 240ms var(--ease-out); }",
      ".c { transition: translate 300ms ease; } /* stylelint-disable-line -- measured against the video */",
      ".d { transition: all var(--dur-1); }",
      ".e { transition: none; }",
      ".f { transition: height var(--dur-2) var(--ease-out); will-change: transform; }",
      ".f:hover { will-change: transform; }",
      "@keyframes grow { from { width: 0; } }",
      "@keyframes card-in { from { opacity: 0; } }",
      ".g { animation: spin 1s linear infinite; }",
      "",
    ].join("\n"),
    "b.css": [
      ".panel { --t-open: 460ms; transition: clip-path var(--t-open) var(--ease-out); }",
      ".panel__dots span { animation: think var(--t-open) infinite; }",
      ".panel__bell:hover svg { animation: ring var(--t-open); }",
      ".panel__tint { transition: background-color var(--t-open); }",
      "@media (prefers-reduced-motion: reduce) {",
      "  .panel, .panel * { transition-duration: 0ms !important; }",
      "  .panel__bell svg { animation: none; }",
      "}",
      "@keyframes card-in { from { opacity: 0; } }",
      "",
    ].join("\n"),
    "c.css": `.lean { --t-lean: 1200ms; transition: transform var(--t-lean) var(--ease-out); }\n@media (prefers-reduced-motion: no-preference) { .wave { animation: wave var(--t-lean) infinite; } }\n`,
    "m.module.css": `@keyframes card-in { from { opacity: 0; } }\n`,
  });
  const r = scan(root, "audit", ".");

  test("flags raw timings, including inside calc(), but not in reduce blocks or disabled lines", () => {
    assert.deepEqual(linesOf(r, "raw-timing", "a.css"), [1, 2, 10]);
    assert.match(hitsOf(r, "raw-timing")[0].note, /inside calc/);
    assert.deepEqual(linesOf(r, "raw-timing", "b.css"), []);
  });

  test("flags transition: all but not transition: none", () => {
    assert.deepEqual(linesOf(r, "transition-all"), [4]);
  });

  test("flags layout properties in transitions and keyframes", () => {
    assert.deepEqual(linesOf(r, "layout-prop", "a.css"), [6, 8]);
  });

  test("flags will-change only on resting selectors", () => {
    assert.deepEqual(linesOf(r, "will-change"), [6]);
  });

  test("flags keyframes defined in two global stylesheets, not in CSS modules", () => {
    assert.deepEqual(hitsOf(r, "dup-keyframes").map((h) => h.file).sort(), ["a.css", "b.css"]);
  });

  test("checks that a file's reduce block reaches each moving rule, for the right kind of property", () => {
    // dots: the reduce rule only zeroes transitions; bell: a rule on the same class covers it; tint: colour only.
    assert.deepEqual(linesOf(r, "no-reduced-motion", "b.css"), [2]);
    assert.deepEqual(hitsOf(r, "infinite").filter((h) => h.file === "b.css").map((h) => h.note), ["still runs under reduced motion"]);
  });

  test("groups a file with no reduce block into one hit, and trusts no-preference and token overrides", () => {
    const hits = hitsOf(r, "no-reduced-motion").filter((h) => h.file === "c.css" || h.file === "a.css");
    assert.deepEqual(hits.map((h) => [h.file, h.line]), [["a.css", 1], ["c.css", 1]]);
    assert.match(hits[1].note, /1 declaration/);
  });
});

describe("audit: JS, Tailwind and libraries", () => {
  const root = project({
    "package.json": JSON.stringify({ dependencies: { tailwindcss: "4", motion: "13", gsap: "3" } }),
    "src/Lean.tsx": [
      "export function Lean() {",
      "  const onPointerMove = (e) => {",
      "    setPos({ x: e.clientX });",
      "  };",
      "  requestAnimationFrame(() => inputRef.current?.focus());",
      "  return <div onPointerMove={onPointerMove} className=\"duration-[250ms] animate-spin motion-safe:animate-ping\" />;",
      "}",
      "",
    ].join("\n"),
    "src/useCount.ts": [
      "export function useCount() {",
      "  const tick = (now) => {",
      "    setValue(now);",
      "    raf = requestAnimationFrame(tick);",
      "  };",
      "  raf = requestAnimationFrame(tick);",
      "  el.animate([{ opacity: 0 }], { duration: 300 });",
      "  window.addEventListener('wheel', onWheel);",
      "  window.addEventListener('touchmove', onTouch, { passive: true });",
      "}",
      "",
    ].join("\n"),
    "src/Card.tsx": `import { motion } from "motion/react";\nexport const Card = () => <motion.div transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }} />;\n`,
    "src/Hero.tsx": `import gsap from "gsap";\nexport function Hero() { useEffect(() => { gsap.to(".x", { y: 10, repeat: -1 }); }, []); }\n`,
    "src/Safe.tsx": `import { useGSAP } from "@gsap/react";\nimport gsap from "gsap";\nexport function Safe() { const reduce = useReducedMotion(); useGSAP(() => { if (!reduce) gsap.to(".y", { x: 5 }); }); }\n`,
    "index.html": `<video autoplay muted loop src="a.mp4"></video>\n<div style="transition: all 0.3s ease"></div>\n`,
    "src/Lean.test.tsx": "setValue(1); requestAnimationFrame(tick);\n",
  });
  const r = scan(root, "audit", ".");

  test("flags state set per frame, but not a one-off next-frame call", () => {
    assert.deepEqual(hitsOf(r, "state-per-frame").map((h) => [h.file, h.line]), [["src/Lean.tsx", 6], ["src/useCount.ts", 4], ["src/useCount.ts", 6]]);
  });

  test("flags rAF loops and element.animate() without a reduced-motion check", () => {
    assert.deepEqual(hitsOf(r, "raf-no-guard").map((h) => h.file), ["src/useCount.ts"]);
    assert.deepEqual(hitsOf(r, "animate-no-guard").map((h) => h.file), ["src/useCount.ts"]);
  });

  test("flags Tailwind arbitrary timings and animate-* without motion-safe", () => {
    assert.deepEqual(hitsOf(r, "tw-arbitrary").map((h) => h.snippet), ["duration-[250ms]"]);
    assert.deepEqual(hitsOf(r, "tw-animate-no-reduce").map((h) => h.snippet), ["animate-spin"]);
  });

  test("flags wheel and touch listeners that aren't passive", () => {
    assert.deepEqual(linesOf(r, "passive-listener"), [8]);
  });

  test("flags motion/react without reduced-motion config, and inline timing literals", () => {
    assert.deepEqual(hitsOf(r, "motion-no-config").map((h) => h.file), ["src/Card.tsx"]);
    assert.ok(hitsOf(r, "js-timing").some((h) => h.file === "src/Card.tsx"));
  });

  test("flags GSAP without cleanup or reduced motion, and its infinite repeat", () => {
    assert.deepEqual(hitsOf(r, "gsap-no-cleanup").map((h) => h.file), ["src/Hero.tsx"]);
    assert.ok(hitsOf(r, "no-reduced-motion").some((h) => h.file === "src/Hero.tsx"));
    assert.ok(!r.hits.some((h) => h.file === "src/Safe.tsx" && h.severity !== "consider"));
    assert.ok(hitsOf(r, "infinite").some((h) => h.file === "src/Hero.tsx"));
  });

  test("checks HTML: looping video and inline styles", () => {
    const html = r.hits.filter((h) => h.file === "index.html").map((h) => h.rule).sort();
    assert.deepEqual(html, ["infinite", "raw-timing", "transition-all"]);
  });

  test("skips test files", () => {
    assert.ok(!r.hits.some((h) => h.file.endsWith(".test.tsx")));
  });
});

describe("audit: global rule and targets", () => {
  test("a page-wide reduce rule counts as handled, a component's own subtree rule doesn't", () => {
    const everything = project({
      "base.css": `@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; } }\n`,
      "a.css": `.a { transition: translate 300ms ease; }\n`,
    });
    assert.deepEqual(hitsOf(scan(everything, "audit", "."), "no-reduced-motion"), []);

    const subtree = project({
      "a.css": `.a { transition: translate 300ms ease; }\n`,
      "b.css": `@media (prefers-reduced-motion: reduce) { .b, .b * { transition-duration: 0ms !important; } }\n`,
    });
    assert.deepEqual(hitsOf(scan(subtree, "audit", "."), "no-reduced-motion").map((h) => h.file), ["a.css"]);
  });

  test("with no paths, audits only what git sees as changed", () => {
    const root = project({ "a.css": `.a { transition: all 1s; }\n`, "b.css": `.b { color: red; }\n` });
    const git = (...args) => spawnSync("git", args, { cwd: root, encoding: "utf8" });
    git("init", "-q");
    git("add", ".");
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init");
    writeFileSync(path.join(root, "b.css"), `.b { transition: all 2s; }\n`);
    writeFileSync(path.join(root, "c.css"), `.c { transition: all 3s; }\n`);
    const r = scan(root, "audit");
    assert.deepEqual([...new Set(r.hits.map((h) => h.file))].sort(), ["b.css", "c.css"]);
  });

  test("outside git, asks for a path", () => {
    const r = scan(project({ "a.css": ".a { transition: all 1s; }\n" }), "audit");
    assert.equal(r.files, 0);
    assert.match(r.note, /pass the files/);
  });
});
