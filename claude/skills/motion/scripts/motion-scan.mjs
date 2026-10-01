#!/usr/bin/env node
// Facts about a project's motion system (`profile`) and candidate motion problems (`audit`).
// No dependencies, so it runs in any repo. Audit hits are candidates: read each one in context before reporting it.
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const USAGE = `Usage:
  node motion-scan.mjs profile [root] [--json]
  node motion-scan.mjs audit [paths...] [--root <dir>] [--json] [--all]

The project root defaults to the nearest folder with a package.json, else the current folder.
audit with no paths checks the files git reports as changed or new; it lists 20 hits per rule unless --all.
A line containing "motion-scan-ignore" or "stylelint-disable" is skipped.`;

// Dot folders (.git, .next, .claude, .scannerwork, .playwright-mcp) are skipped as well.
const SKIP_DIRS = new Set(["node_modules", "dist", "build", "out", "coverage", "vendor", "target", "storybook-static", "__pycache__"]);
const CSS_EXT = /\.(css|scss|sass|less|pcss)$/i;
const MARKUP_EXT = /\.(html?|vue|svelte|astro)$/i;
const JS_EXT = /\.(m?[jt]sx?|cjs)$/i;
const SKIP_FILE = /\.(min\.(js|css)|d\.ts|map)$/i;
// Build output that isn't the project's own code: hashed chunks (index-BOVmcLe6.css), bundles, "Save page as" folders.
const isGeneratedFile = (name) => {
  if (/(^|[._-])bundle[._-]/i.test(name)) return true;
  const hash = name.match(/[-.]([A-Za-z0-9_]{8,})\.(css|m?js)$/)?.[1];
  return Boolean(hash && (/\d/.test(hash) || (/[a-z]/.test(hash) && /[A-Z]/.test(hash))));
};
const GENERATED_DIR = /_files$/;
const looksMinified = (text) => text.split("\n", 400).some((l) => l.length > 5000);
const TEST_FILE = /(\.(test|spec|stories)\.|(^|\/)(test|tests|__tests__|e2e)\/)/i;
const MAX_BYTES = 512 * 1024;
const MAX_FILES = 10000;

const MOTION_LIBS = ["motion", "framer-motion", "gsap", "@gsap/react", "@react-spring/web", "react-spring", "lottie-web", "lottie-react", "@lottiefiles/dotlottie-web", "@lottiefiles/dotlottie-react", "animejs", "tw-animate-css", "tailwindcss-animate", "animate.css", "three", "@react-three/fiber", "@react-three/drei", "@rive-app/react-canvas", "@rive-app/canvas", "lenis", "locomotive-scroll", "@formkit/auto-animate", "aos", "swiper"];
const FRAMEWORKS = [["next", "Next"], ["astro", "Astro"], ["@sveltejs/kit", "SvelteKit"], ["nuxt", "Nuxt"], ["@remix-run/react", "Remix"], ["@angular/core", "Angular"], ["vue", "Vue"], ["svelte", "Svelte"], ["solid-js", "Solid"], ["react", "React"], ["vite", "Vite"]];
const LOCKFILES = [["pnpm-lock.yaml", "pnpm"], ["yarn.lock", "yarn"], ["bun.lockb", "bun"], ["bun.lock", "bun"], ["package-lock.json", "npm"]];
const SCRIPT_KEYS = /^(lint|build|test|typecheck|type-check|tsc|check)(:|$)/;

// Properties whose transition or keyframes make the browser redo layout every frame.
const LAYOUT_PROPS = new Set(["width", "height", "min-width", "min-height", "max-width", "max-height", "top", "left", "right", "bottom", "inset", "inset-block", "inset-inline", "margin", "margin-top", "margin-right", "margin-bottom", "margin-left", "margin-block", "margin-inline", "padding", "padding-top", "padding-right", "padding-bottom", "padding-left", "padding-block", "padding-inline", "font-size", "letter-spacing", "gap", "border-width"]);
// A transition of only these is fine under reduced motion: nothing moves.
const STILL_PROPS = new Set(["color", "background-color", "background", "border-color", "outline-color", "text-decoration-color", "fill", "stroke", "opacity", "box-shadow", "visibility", "caret-color", "column-rule-color"]);
const TIMING_PROPS = new Set(["transition", "transition-property", "transition-duration", "transition-delay", "transition-timing-function", "animation", "animation-duration", "animation-delay", "animation-timing-function", "animation-iteration-count"]);
const TIMING_WORDS = new Set(["ease", "ease-in", "ease-out", "ease-in-out", "linear", "step-start", "step-end", "infinite", "normal", "reverse", "alternate", "alternate-reverse", "forwards", "backwards", "both", "none", "running", "paused", "allow-discrete", "initial", "inherit", "unset"]);
const JS_REDUCE_CHECK = /prefers-reduced-motion|reducedMotion|useReducedMotion|shouldReduce|prefersReduced|reduceMotion|isReduced/i;

const TIME = /(?<![\w.#-])(\d*\.?\d+)(ms|s)\b/g;
const IS_TIME = /^-?\d*\.?\d+m?s$/;
const IS_EASING_FN = /^(cubic-bezier|linear|steps)\(/;

const SEVERITY = {
  "raw-timing": "must",
  "no-reduced-motion": "must",
  "state-per-frame": "must",
  "raf-no-guard": "must",
  "animate-no-guard": "must",
  infinite: "must",
  "layout-prop": "must",
  "transition-all": "should",
  "will-change": "should",
  "dup-keyframes": "should",
  "tw-arbitrary": "should",
  "tw-animate-no-reduce": "should",
  "passive-listener": "should",
  "motion-no-config": "should",
  "gsap-no-cleanup": "should",
  "js-timing": "consider",
};

const RULE_TEXT = {
  "raw-timing": "raw duration or easing in a transition/animation: use a token, or a named local timing defined at the top of the root rule",
  "no-reduced-motion": "moving animation with custom timing and no reduced-motion handling in this file (and no global rule)",
  "state-per-frame": "framework state set from a per-frame handler: write a CSS custom property through a ref, or use a motion value",
  "raf-no-guard": "requestAnimationFrame in a file with no reduced-motion check",
  "animate-no-guard": "element.animate() in a file with no reduced-motion check",
  infinite: "infinite animation: fine for a live state (loading, listening); ambient motion needs an off-screen/hidden-tab pause, reduced motion off, and a pause control past 5s",
  "layout-prop": "animates a layout property: use transform/translate/scale, clip-path or opacity",
  "transition-all": "transition: all animates properties nobody chose: list them",
  "will-change": "will-change on a resting selector: set it just before the animation, or drop it",
  "dup-keyframes": "keyframes name defined more than once: the later one silently wins",
  "tw-arbitrary": "Tailwind arbitrary timing: add a theme token instead",
  "tw-animate-no-reduce": "Tailwind animate-* without motion-safe:/motion-reduce:, and no global reduced-motion rule",
  "passive-listener": "wheel/touch listener without { passive: true } makes scrolling wait for it (fine if it calls preventDefault)",
  "motion-no-config": "motion/react used without MotionConfig reducedMotion=\"user\" in the project or useReducedMotion in this file",
  "gsap-no-cleanup": "GSAP tweens in a component without useGSAP() or gsap.context() cleanup",
  "js-timing": "timing literals in JS animation options: share them from one presets module that mirrors the CSS tokens",
};

export function walk(root) {
  const files = [];
  const stack = [root];
  while (stack.length && files.length < MAX_FILES) {
    const dir = stack.pop();
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!entry.name.startsWith(".") && !SKIP_DIRS.has(entry.name) && !GENERATED_DIR.test(entry.name)) stack.push(full);
      } else if (entry.isFile() && !SKIP_FILE.test(entry.name) && !isGeneratedFile(entry.name)) {
        files.push(full);
      }
    }
  }
  return files;
}

const isSource = (file) => CSS_EXT.test(file) || MARKUP_EXT.test(file) || JS_EXT.test(file);
const toPosix = (p) => p.split(path.sep).join("/");
const relTo = (root, file) => toPosix(path.relative(root, file)) || ".";

// A source file's text, or null when it's too big, minified or unreadable.
function read(file) {
  try {
    if (statSync(file).size > MAX_BYTES) return null;
    const text = readFileSync(file, "utf8");
    return isSource(file) && looksMinified(text) ? null : text;
  } catch {
    return null;
  }
}

function lineStarts(text) {
  const starts = [0];
  for (let i = 0; i < text.length; i++) if (text[i] === "\n") starts.push(i + 1);
  return starts;
}

function lineAt(starts, index) {
  let lo = 0;
  let hi = starts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (starts[mid] <= index) lo = mid;
    else hi = mid - 1;
  }
  return lo + 1;
}

/**
 * A small CSS reader: every declaration with its line and the chain of block
 * preludes around it (`@layer x`, `@media (...)`, `.card:hover`), plus every block.
 * Comments are skipped; `;`, `{` and `}` inside strings, parentheses or SCSS `#{}` don't count.
 */
export function parseCss(code, { firstLine = 1, lineComments = false } = {}) {
  const decls = [];
  const blocks = [];
  const stack = [];
  let buf = "";
  let bufLine = firstLine;
  let line = firstLine;
  let parens = 0;

  const emit = () => {
    const text = buf.trim();
    buf = "";
    if (!stack.length || !text) return;
    const colon = text.indexOf(":");
    if (colon <= 0) return;
    const rawProp = text.slice(0, colon).trim();
    if (/\s/.test(rawProp) || rawProp.startsWith("@")) return;
    const prop = rawProp.startsWith("--") ? rawProp : rawProp.toLowerCase();
    const value = text.slice(colon + 1).trim();
    decls.push({ prop, value, line: bufLine, lines: (value.match(/\n/g) ?? []).length + 1, stack: [...stack] });
  };

  // Copies code[i..close] into the buffer, counting newlines, and returns the index of `close`.
  const copyUntil = (i, close) => {
    let j = i + 1;
    while (j < code.length && code[j] !== close) {
      if (code[j] === "\\") j++;
      else if (code[j] === "\n") line++;
      j++;
    }
    buf += code.slice(i, j + 1);
    return j;
  };

  for (let i = 0; i < code.length; i++) {
    const c = code[i];
    if (c === "/" && code[i + 1] === "*") {
      const end = code.indexOf("*/", i + 2);
      const stop = end === -1 ? code.length : end + 2;
      for (let j = i; j < stop; j++) if (code[j] === "\n") line++;
      i = stop - 1;
      continue;
    }
    if (lineComments && c === "/" && code[i + 1] === "/" && parens === 0 && (i === 0 || /[\s;{}]/.test(code[i - 1]))) {
      const end = code.indexOf("\n", i);
      i = (end === -1 ? code.length : end) - 1;
      continue;
    }
    if (c === "\n") line++;
    if (!buf.trim() && !/\s/.test(c)) bufLine = line;
    if (c === '"' || c === "'") {
      i = copyUntil(i, c);
      continue;
    }
    if (c === "#" && code[i + 1] === "{") {
      i = copyUntil(i + 1, "}");
      continue;
    }
    if (c === "(") parens++;
    else if (c === ")") parens = Math.max(0, parens - 1);
    if (parens > 0) {
      buf += c;
      continue;
    }
    if (c === "{") {
      const prelude = buf.trim().replace(/\s+/g, " ");
      blocks.push({ prelude, line: bufLine, depth: stack.length });
      stack.push(prelude);
      buf = "";
    } else if (c === ";") {
      emit();
    } else if (c === "}") {
      emit();
      stack.pop();
    } else {
      buf += c;
    }
  }
  return { decls, blocks };
}

export function styleBlocks(markup) {
  const out = [];
  for (const m of markup.matchAll(/<style\b([^>]*)>([\s\S]*?)<\/style>/gi)) {
    const start = m.index + m[0].indexOf(">") + 1;
    const firstLine = (markup.slice(0, start).match(/\n/g) ?? []).length + 1;
    out.push({ code: m[2], firstLine, lineComments: /lang=["']?(scss|less|sass)/i.test(m[1]) });
  }
  return out;
}

function cssOf(file, text) {
  if (CSS_EXT.test(file)) return [parseCss(text, { lineComments: /\.(scss|sass|less)$/i.test(file) })];
  if (MARKUP_EXT.test(file)) return styleBlocks(text).map((b) => parseCss(b.code, b));
  return [];
}

const inReduce = (stack) => stack.some((p) => /prefers-reduced-motion\s*:\s*reduce/i.test(p));
const inNoPreference = (stack) => stack.some((p) => /prefers-reduced-motion\s*:\s*no-preference/i.test(p));
const inKeyframes = (stack) => stack.some((p) => /^@(-webkit-)?keyframes\b/i.test(p));
const inTheme = (stack) => stack.some((p) => /^@theme\b/i.test(p));
const selectorOf = (stack) => [...stack].reverse().find((p) => !p.startsWith("@")) ?? "";
const isGlobalScope = (stack) => inTheme(stack) || /^(:root|html|:host|body)\b/.test(selectorOf(stack)) || !selectorOf(stack);
// `*, *::before, *::after` or `html *`: every element on the page, not one component's subtree.
const isEverything = (selector) => selector.split(",").every((part) => /^((html|:root|body)\s+)?\*(::?(before|after|backdrop|marker))?$/.test(part.trim()));
const keyframesName = (prelude) => prelude.match(/^@(?:-webkit-)?keyframes\s+([\w-]+)/i)?.[1];

export function stripVars(value) {
  let out = value;
  for (let start = out.indexOf("var("); start !== -1; start = out.indexOf("var(")) {
    let depth = 0;
    let end = start + 3;
    for (; end < out.length; end++) {
      if (out[end] === "(") depth++;
      else if (out[end] === ")" && --depth === 0) break;
    }
    out = out.slice(0, start) + " " + out.slice(end + 1);
  }
  return out;
}

const rawTimes = (value) => [...stripVars(value).matchAll(TIME)].filter((m) => Number(m[1]) !== 0).map((m) => m[0]);
const rawEasings = (value) => [...stripVars(value).matchAll(/\b(cubic-bezier|linear|steps)\(/g)].map((m) => m[1] + "()");
const varNames = (value) => [...value.matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1]);

/** What kind of motion value a custom property holds, judged by its value, never its name. */
export function motionKind(value) {
  const v = value.replace(/\s*!important$/, "").trim();
  if (IS_TIME.test(v)) return "duration";
  if (IS_EASING_FN.test(v) || /^(ease|ease-in|ease-out|ease-in-out|linear|step-start|step-end)$/.test(v)) return "easing";
  if (/^var\(--[\w-]+\)$/.test(v)) return "alias";
  const sized = /#|\d(px|rem|em|%|vw|vh|dvh|svh|deg|fr|ch|ex)\b/.test(v);
  if (/^calc\(/.test(v) && /\d(ms|s)\b/.test(v) && !sized) return "duration";
  if (/(?<![\w.#-])\d*\.?\d+m?s\b/.test(v) && /\s/.test(v) && !sized) return "shorthand";
  return null;
}

// Splits a transition/animation value into its comma-separated layers.
function layers(value) {
  const out = [];
  let depth = 0;
  let cur = "";
  for (const c of value) {
    if (c === "(") depth++;
    else if (c === ")") depth--;
    if (c === "," && depth === 0) {
      out.push(cur.trim());
      cur = "";
    } else cur += c;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

// The properties a transition declaration animates ("all" when it names none).
function transitionedProps(prop, value) {
  if (/^(none|initial|inherit|unset)$/i.test(value.trim())) return [];
  if (prop === "transition-property") return layers(value).map((v) => v.toLowerCase());
  if (prop !== "transition") return [];
  return layers(value).map((layer) => {
    const words = stripVars(layer).split(/\s+/).filter(Boolean);
    const name = words.find((w) => !IS_TIME.test(w) && !TIMING_WORDS.has(w) && !IS_EASING_FN.test(w));
    if (name) return name.toLowerCase();
    return !words.length && layer.includes("var(") ? "unknown" : "all";
  });
}

function readPackages(root, files) {
  const pkgs = [];
  for (const file of files.filter((f) => path.basename(f) === "package.json")) {
    try {
      pkgs.push({ dir: relTo(root, path.dirname(file)), json: JSON.parse(readFileSync(file, "utf8")) });
    } catch {
      // not valid JSON
    }
  }
  return pkgs.sort((a, b) => a.dir.length - b.dir.length);
}

function packageManager(dir) {
  for (const [lock, name] of LOCKFILES) if (existsSync(path.join(dir, lock))) return name;
  return null;
}

/** Everything both commands need to know about the project, from one pass over its files. */
export function scanProject(root) {
  const all = walk(root);
  const pkgs = readPackages(root, all);
  const deps = new Map();
  for (const { dir, json } of pkgs) {
    for (const [name, version] of Object.entries({ ...json.dependencies, ...json.devDependencies })) {
      if (!deps.has(name)) deps.set(name, { version, dir });
    }
  }

  const props = [];
  const keyframes = new Map();
  const blocks = [];
  const globalRules = [];
  const texts = new Map();
  for (const file of all.filter(isSource)) {
    const text = read(file);
    if (text === null) continue;
    texts.set(file, text);
    for (const css of cssOf(file, text)) {
      for (const d of css.decls) {
        if (d.prop.startsWith("--")) props.push({ ...d, file, kind: motionKind(d.value) });
        if (inReduce(d.stack) && isEverything(selectorOf(d.stack)) && /^(animation|transition)(-duration)?$/.test(d.prop)) {
          globalRules.push({ file, line: d.line, value: d.value });
        }
      }
      for (const b of css.blocks) {
        blocks.push({ ...b, file });
        // CSS modules, Vue and Svelte scope their keyframe names, so only global stylesheets can clash.
        const name = keyframesName(b.prelude);
        if (name && !/\.module\./.test(file) && (CSS_EXT.test(file) || /\.html?$/i.test(file))) {
          if (!keyframes.has(name)) keyframes.set(name, []);
          keyframes.get(name).push({ file, line: b.line });
        }
      }
    }
  }

  // Aliases such as `--duration-fast: var(--dur-1)` take the kind of what they point to.
  const kindOf = new Map();
  for (const p of props) if (p.kind && p.kind !== "alias") kindOf.set(p.prop, p.kind);
  for (let pass = 0; pass < 3; pass++) {
    for (const p of props) {
      const target = p.kind === "alias" ? varNames(p.value)[0] : null;
      if (target && kindOf.has(target)) kindOf.set(p.prop, kindOf.get(target));
    }
  }
  const isMotion = (p) => (p.kind === "alias" ? kindOf.has(varNames(p.value)[0]) : Boolean(p.kind));
  const motionProps = props.filter(isMotion);
  const tokens = motionProps.filter((p) => isGlobalScope(p.stack) && !inReduce(p.stack));
  const tokenNames = new Set(tokens.map((t) => t.prop));
  const reduceOverrides = motionProps.filter((p) => inReduce(p.stack) && tokenNames.has(p.prop));
  const reducing = new Set(reduceOverrides.map((p) => p.prop));
  const locals = motionProps.filter((p) => !isGlobalScope(p.stack) && !inReduce(p.stack));

  const usesTailwind = deps.has("tailwindcss") || [...texts.values()].some((t) => /@import\s+["']tailwindcss|@tailwind\s+(base|utilities)/.test(t));
  const motionConfig = [...texts].filter(([, t]) => /<MotionConfig\b[^>]*reducedMotion/.test(t)).map(([f]) => f);

  return { root, all, texts, pkgs, deps, tokens, reduceOverrides, reducing, locals, kindOf, keyframes, blocks, globalRules, usesTailwind, motionConfig };
}

const prefixOf = (name) => name.match(/^(--[a-z0-9]+)-/i)?.[1].concat("-*") ?? name;

function summarizeProfile(p) {
  const { root, texts } = p;
  const rel = (f) => relTo(root, f);
  const rootPkg = p.pkgs.find((pkg) => pkg.dir === ".") ?? p.pkgs[0];
  const scripts = Object.entries(rootPkg?.json.scripts ?? {}).filter(([k]) => SCRIPT_KEYS.test(k));

  const byPrefix = new Map();
  for (const l of p.locals) {
    const prefix = prefixOf(l.prop);
    const entry = byPrefix.get(prefix) ?? { count: 0, files: new Set(), kinds: new Set() };
    entry.count++;
    entry.files.add(rel(l.file));
    entry.kinds.add(p.kindOf.get(l.prop));
    byPrefix.set(prefix, entry);
  }

  const jsConstants = [];
  const inlineEase = [];
  const helpers = [];
  const jsChecks = { matchMedia: 0, useReducedMotion: 0, "reducedMotion()": 0, "gsap.matchMedia": 0 };
  let twVariants = 0;
  const tests = [];
  for (const [file, text] of texts) {
    if (!JS_EXT.test(file) && !MARKUP_EXT.test(file)) continue;
    const starts = lineStarts(text);
    const isTest = TEST_FILE.test(toPosix(file)) || /setup/i.test(path.basename(file));
    for (const m of text.matchAll(/export\s+const\s+([A-Z][A-Z0-9_]*)\s*=\s*\{/g)) {
      if (/ANIM|MOTION|DURATION|EASE|EASING|TIMING|DELAY|STAGGER|TRANSITION|SPRING|SCROLL/.test(m[1])) jsConstants.push(`${rel(file)}:${lineAt(starts, m.index)} ${m[1]}`);
    }
    for (const m of text.matchAll(/(?:export\s+)?const\s+([A-Z][A-Z0-9_]*)\s*=\s*(\d+(?:\.\d+)?)\s*[;,\n]/g)) {
      if (/(^|_)(MS|DURATION|DELAY|STAGGER|FADE|ENTER|EXIT|RESIZE|EASE)(_|$)/.test(m[1])) jsConstants.push(`${rel(file)}:${lineAt(starts, m.index)} ${m[1]} = ${m[2]}`);
    }
    const eases = text.match(/\bease\s*:\s*\[\s*[\d.]+\s*,/g);
    if (eases) inlineEase.push(`${rel(file)} (${eases.length})`);
    const names = [...text.matchAll(/export\s+(?:default\s+)?(?:async\s+)?(?:function\*?|const|let|class)\s+([A-Za-z_$][\w$]*)/g)].map((m) => m[1]);
    const motionHelpers = names.filter((n) => /tween|count.?up|in.?view|reduced.?motion|restart.?class|reflow|spring|damp|visibility.?pause|swap.?content|dissolve|scroll.?(anim|reveal)|fade.?in|stagger|^ease$|^animate/i.test(n));
    if (motionHelpers.length && !isTest) helpers.push(`${rel(file)} (${motionHelpers.join(", ")})`);
    if (/matchMedia\([^)]*prefers-reduced-motion/.test(text)) jsChecks.matchMedia++;
    if (/\buseReducedMotion\(/.test(text)) jsChecks.useReducedMotion++;
    if (/\breducedMotion\(\)/.test(text)) jsChecks["reducedMotion()"]++;
    if (/gsap\.matchMedia\(/.test(text)) jsChecks["gsap.matchMedia"]++;
    twVariants += (text.match(/\bmotion-(reduce|safe):/g) ?? []).length;
    if (isTest && /prefers-reduced-motion|reducedMotion\s*:\s*["']reduce/.test(text)) tests.push(rel(file));
  }

  const reduceBlocks = p.blocks.filter((b) => /prefers-reduced-motion\s*:\s*reduce/i.test(b.prelude));
  const noPrefBlocks = p.blocks.filter((b) => /prefers-reduced-motion\s*:\s*no-preference/i.test(b.prelude));

  const docs = [];
  for (const file of p.all.filter((f) => /\.mdx?$/i.test(f))) {
    const name = path.basename(file);
    const r = rel(file);
    const motionNamed = /motion|animation/i.test(name);
    if (!motionNamed && !/^(CLAUDE|AGENTS|README|ART_DIRECTION|DESIGN|PRODUCT|STYLEGUIDE)\.md$/i.test(name) && !r.startsWith("docs/")) continue;
    const text = read(file);
    if (text === null) continue;
    const starts = lineStarts(text);
    const headings = [...text.matchAll(/^#{1,6}\s+.*\b(motion|animations?|reduced motion|choreography)\b.*$/gim)].map((m) => `${lineAt(starts, m.index)} "${m[0].trim()}"`);
    if (motionNamed) docs.push(`${r}${headings.length ? ` (${headings.length} motion headings)` : ""}`);
    else for (const h of headings.slice(0, 3)) docs.push(`${r}:${h}`);
  }

  const lint = [];
  for (const file of p.all.filter((f) => /^(\.stylelintrc(\.\w+)?|stylelint\.config\.\w+)$/.test(path.basename(f)))) {
    lint.push(/transition|animation/.test(read(file) ?? "") ? `${rel(file)} checks transition/animation values` : `${rel(file)} (no motion rules)`);
  }

  return {
    root: toPosix(root),
    stack: {
      frameworks: FRAMEWORKS.filter(([dep]) => p.deps.has(dep)).map(([, name]) => name),
      packageManager: packageManager(rootPkg ? path.join(root, rootPkg.dir) : root),
      packages: p.pkgs.map((pkg) => pkg.dir),
      tailwind: p.usesTailwind,
      libraries: MOTION_LIBS.filter((lib) => p.deps.has(lib)).map((lib) => `${lib} ${p.deps.get(lib).version}`),
      scripts: Object.fromEntries(scripts),
    },
    tokens: p.tokens.map((t) => ({ name: t.prop, value: t.value.replace(/\s+/g, " "), kind: p.kindOf.get(t.prop), at: `${rel(t.file)}:${t.line}`, theme: inTheme(t.stack) })),
    reducedMotionOverrides: p.reduceOverrides.map((o) => `${o.prop}: ${o.value}`),
    localTimings: [...byPrefix].sort((a, b) => b[1].count - a[1].count).slice(0, 8).map(([prefix, e]) => ({ prefix, count: e.count, files: e.files.size, kinds: [...e.kinds] })),
    jsTimings: { constants: jsConstants.slice(0, 12), inlineEaseArrays: inlineEase.slice(0, 8) },
    reducedMotion: {
      tokenOverride: p.reduceOverrides.length,
      globalRules: p.globalRules.map((g) => `${rel(g.file)}:${g.line} ${g.value}`),
      reduceBlocks: reduceBlocks.length,
      reduceBlockFiles: new Set(reduceBlocks.map((b) => b.file)).size,
      noPreferenceBlocks: noPrefBlocks.length,
      tailwindVariants: twVariants,
      js: jsChecks,
      motionConfig: p.motionConfig.map(rel),
    },
    keyframes: p.keyframes.size,
    helpers,
    docs,
    lint,
    tests,
    empty: !p.tokens.length && !reduceBlocks.length && !p.globalRules.length && !docs.length,
  };
}

function printProfile(s) {
  const out = [`# Motion profile: ${s.root}`, ""];
  const st = s.stack;
  const kind = st.frameworks.join(" + ") || (st.packages.length ? "JS" : "plain HTML/CSS/JS (no package.json)");
  out.push(`Stack: ${kind}${st.tailwind ? " + Tailwind" : ""} | ${st.packageManager ?? "no lockfile"} | ${st.libraries.length ? st.libraries.join(", ") : "no animation library"}`);
  if (st.packages.length > 1) out.push(`Packages: ${st.packages.join(", ")}`);
  const scripts = Object.entries(st.scripts);
  out.push(`Scripts: ${scripts.length ? scripts.map(([k, v]) => `${k} \`${v}\``).join(" | ") : "none for lint/build/test"}`);

  const byFile = new Map();
  for (const t of s.tokens) {
    const file = t.at.replace(/:\d+$/, "");
    if (!byFile.has(file)) byFile.set(file, []);
    byFile.get(file).push(t);
  }
  if (byFile.size) {
    out.push("Tokens:");
    for (const [file, list] of byFile) {
      const shown = list.slice(0, 14).map((t) => `${t.name} ${t.value}`).join(", ");
      out.push(`  ${file}:${list[0].at.split(":").pop()}${list.some((t) => t.theme) ? " (@theme)" : ""}: ${shown}${list.length > 14 ? ` … +${list.length - 14}` : ""}`);
    }
  } else out.push("Tokens: none (no global custom property holds a duration or easing)");
  if (s.reducedMotionOverrides.length) out.push(`  Under reduced motion: ${s.reducedMotionOverrides.join(", ")}`);
  if (s.localTimings.length) out.push(`Local timings: ${s.localTimings.map((l) => `${l.prefix} x${l.count} in ${l.files} files (${l.kinds.join("/")})`).join("; ")}`);
  if (s.jsTimings.constants.length) out.push(`JS timing constants: ${s.jsTimings.constants.join("; ")}`);
  if (s.jsTimings.inlineEaseArrays.length) out.push(`Inline ease arrays: ${s.jsTimings.inlineEaseArrays.join(", ")}`);

  const rm = s.reducedMotion;
  const parts = [];
  if (rm.tokenOverride) parts.push(`token override (${rm.tokenOverride} tokens)`);
  if (rm.globalRules.length) parts.push(`global rule at ${rm.globalRules.join("; ")}`);
  if (rm.reduceBlocks) parts.push(`${rm.reduceBlocks} @media (reduce) blocks in ${rm.reduceBlockFiles} files`);
  if (rm.noPreferenceBlocks) parts.push(`${rm.noPreferenceBlocks} no-preference blocks`);
  if (rm.tailwindVariants) parts.push(`${rm.tailwindVariants} motion-safe/motion-reduce classes`);
  const js = Object.entries(rm.js).filter(([, n]) => n).map(([k, n]) => `${k} in ${n} files`);
  if (js.length) parts.push(`JS: ${js.join(", ")}`);
  if (rm.motionConfig.length) parts.push(`MotionConfig reducedMotion in ${rm.motionConfig.join(", ")}`);
  else if (st.libraries.some((l) => /^(motion|framer-motion) /.test(l))) parts.push("no MotionConfig reducedMotion");
  out.push(`Reduced motion: ${parts.join(" | ") || "nothing found"}`);
  out.push(`Keyframes: ${s.keyframes} global names`);
  out.push(`Helpers: ${s.helpers.length ? s.helpers.join("; ") : "none found"}`);
  out.push(`Docs: ${s.docs.length ? s.docs.join("; ") : "none mention motion"}`);
  out.push(`Lint: ${s.lint.length ? s.lint.join("; ") : "no stylelint config"}`);
  if (s.tests.length) out.push(`Tests: reduced motion mocked or emulated in ${s.tests.join(", ")}`);
  if (s.empty) out.push("", "No motion system found. `/motion init` can set one up.");
  return out.join("\n");
}

function changedFiles(root) {
  const git = (args) => {
    try {
      return execFileSync("git", args, { cwd: root, stdio: ["ignore", "pipe", "ignore"] }).toString().split("\n").filter(Boolean);
    } catch {
      return null;
    }
  };
  const top = git(["rev-parse", "--show-toplevel"]);
  if (!top) return null;
  const tracked = git(["diff", "--name-only", "HEAD"]) ?? git(["diff", "--name-only", "--cached"]) ?? [];
  const untracked = git(["ls-files", "--others", "--exclude-standard"]) ?? [];
  return [...new Set([...tracked, ...untracked])].map((n) => path.resolve(top[0], n));
}

function targetFiles(root, paths) {
  if (!paths.length) {
    const changed = changedFiles(root);
    if (changed === null) return { files: [], note: "Not a git repository: pass the files or folders to audit." };
    const inside = changed.filter((f) => !relTo(root, f).startsWith("..") && existsSync(f) && isSource(f));
    return { files: inside, note: inside.length ? `Changed files (${inside.length}).` : "No changed source files: pass the files or folders to audit." };
  }
  const files = [];
  for (const p of paths) {
    const abs = path.resolve(p);
    if (!existsSync(abs)) continue;
    if (statSync(abs).isDirectory()) files.push(...walk(abs).filter(isSource));
    else if (isSource(abs)) files.push(abs);
  }
  const unique = [...new Set(files)];
  return { files: unique, note: `${unique.length} files under ${paths.join(", ")}.` };
}

// The source of a function: its `{ … }` body, or the expression after `=>`.
function bodyFrom(text, from) {
  const arrow = text.indexOf("=>", from);
  const near = arrow !== -1 && arrow - from < 300;
  let i = near ? arrow + 2 : from;
  while (i < text.length && /\s/.test(text[i])) i++;
  if (text[i] !== "{") {
    if (near) {
      const end = text.indexOf("\n", i);
      return text.slice(i, end === -1 ? undefined : end);
    }
    i = text.indexOf("{", from);
    if (i === -1) return "";
  }
  let depth = 0;
  for (let j = i; j < text.length; j++) {
    if (text[j] === "{") depth++;
    else if (text[j] === "}" && --depth === 0) return text.slice(i, j + 1);
  }
  return text.slice(i);
}

// Handlers that run every frame. `loop` means only a callback that schedules itself counts.
const PER_FRAME = [
  { re: /\bon(?:Pointer|Mouse|Touch)Move\s*=\s*\{/g },
  { re: /\bon(?:Scroll|Wheel|Drag)\s*=\s*\{/g },
  { re: /addEventListener\(\s*["'](?:pointermove|mousemove|touchmove|scroll|wheel)["']\s*,/g },
  { re: /\brequestAnimationFrame\(/g, loop: true },
  { re: /\buseFrame\(/g },
  { re: /\buseAnimationFrame\(/g },
];
const SETTER = /(?<![.\w$])(set[A-Z]\w*)\s*\(/g;
const NOT_STATE = new Set(["setTimeout", "setInterval", "setImmediate"]);

// The callback passed to the call that ends at `end`: a named function's body, or the inline one.
function callbackBody(text, end) {
  const named = text.slice(end).match(/^\s*(?:this\.)?([A-Za-z_$][\w$]*)\s*[)},]/);
  if (!named) return bodyFrom(text, end);
  const def = text.match(new RegExp(`(?:const|let|var|function)\\s+${named[1]}\\b`));
  return def ? bodyFrom(text, def.index) : "";
}

const classesOf = (selector) => selector.match(/\.[\w-]+/g) ?? [];
const lastCompound = (part) => part.split(/\s*[\s>+~]\s*/).filter(Boolean).pop() ?? "";
const bare = (compound) => compound.replace(/:{1,2}[\w-]+(\([^)]*\))?/g, "");

/**
 * Whether a file's own reduced-motion blocks reach a declaration: a reduce rule for the same
 * kind of property (animation or transition) on the same selector, on the same element class,
 * or `.block *` over its subtree (BEM children count); or every custom timing it uses reset under reduce.
 */
function reduceCoverage(css, project) {
  const reduced = css.decls.filter((d) => inReduce(d.stack));
  const rules = reduced
    .filter((d) => /^(animation|transition)/.test(d.prop))
    .flatMap((d) => selectorOf(d.stack).split(",").map((p) => ({ part: p.trim(), kind: d.prop.split("-")[0] })))
    .filter((r) => r.part);
  const vars = new Set(reduced.filter((d) => d.prop.startsWith("--")).map((d) => d.prop));
  const inSubtree = (cls, base) => cls === base || cls.startsWith(`${base}__`) || cls.startsWith(`${base}-`);
  const partCovered = (part, kind) =>
    rules.some((r) => {
      if (r.kind !== kind) return false;
      if (r.part === part) return true;
      if (/\*$/.test(r.part)) {
        const base = classesOf(r.part.replace(/\s*\*$/, ""));
        if (base.length && base.every((b) => classesOf(part).some((c) => inSubtree(c, b)))) return true;
      }
      const mine = classesOf(lastCompound(part));
      if (mine.length) return mine.some((c) => classesOf(lastCompound(r.part)).includes(c));
      // `.bell:hover svg` is reached by `.bell svg`, but not by `.bell` alone (that's the parent).
      return bare(lastCompound(r.part)) === bare(lastCompound(part)) && classesOf(part).some((c) => classesOf(r.part).includes(c));
    });
  return (selector, prop, value) => {
    const timings = varNames(value).filter((v) => ["duration", "shorthand"].includes(project.kindOf.get(v)));
    if (!rawTimes(value).length && timings.length && timings.every((v) => vars.has(v) || project.reducing.has(v))) return true;
    const kind = prop.split("-")[0];
    return selector.split(",").every((p) => partCovered(p.trim(), kind));
  };
}

export function auditFile(file, text, project) {
  const hits = [];
  const rel = relTo(project.root, file);
  const lines = text.split("\n");
  const ignored = (line, span = 1) => lines.slice(line - 1, line - 1 + span).some((l) => /stylelint-disable|motion-scan-ignore/.test(l));
  const add = (rule, line, snippet, note) => hits.push({ rule, severity: SEVERITY[rule], file: rel, line, snippet: String(snippet ?? "").replace(/\s+/g, " ").trim().slice(0, 140), note });
  const globalRule = project.globalRules.length > 0;

  // Custom timing (raw, or a variable that doesn't drop to 0 under reduce) on something that moves.
  // Colour and opacity changes don't count: they're fine under reduced motion.
  const isCustom = (v) => rawTimes(v).length > 0 || varNames(v).some((n) => ["duration", "shorthand"].includes(project.kindOf.get(n)) && !project.reducing.has(n));
  const movesWithCustomTiming = (prop, value) => {
    if (prop === "transition") return layers(value).some((layer) => !STILL_PROPS.has(transitionedProps(prop, layer)[0]) && isCustom(layer));
    if (prop === "transition-property") return false;
    return isCustom(value);
  };

  const checkTiming =(prop, value, line, guarded) => {
    const snippet = `${prop}: ${value}`;
    const times = rawTimes(value);
    const easings = rawEasings(value);
    if (times.length || easings.length) {
      const inCalc = /calc\([^)]*\d(ms|s)\b/.test(stripVars(value));
      add("raw-timing", line, snippet, [...times, ...easings].join(", ") + (inCalc ? " (inside calc(), which lint rules usually miss)" : ""));
    }
    const animated = transitionedProps(prop, value);
    if (animated.includes("all")) add("transition-all", line, snippet);
    const layout = animated.filter((a) => LAYOUT_PROPS.has(a));
    if (layout.length) add("layout-prop", line, snippet, layout.join(", "));
    if (/^animation(-iteration-count)?$/.test(prop) && /\binfinite\b/.test(value)) {
      add("infinite", line, snippet, guarded ? "off under reduced motion; check it's a live state or guarded ambient motion" : "still runs under reduced motion");
    }
  };

  for (const css of cssOf(file, text)) {
    const hasReduceBlock = css.blocks.some((b) => /prefers-reduced-motion\s*:\s*reduce/i.test(b.prelude));
    const covered = reduceCoverage(css, project);
    let unguarded = null;
    let unguardedCount = 0;
    for (const d of css.decls) {
      if (ignored(d.line, d.lines)) continue;
      if (inKeyframes(d.stack)) {
        if (LAYOUT_PROPS.has(d.prop)) add("layout-prop", d.line, `${d.prop}: ${d.value}`, `inside ${d.stack.find((p) => /keyframes/i.test(p))}`);
        continue;
      }
      if (d.prop === "will-change" && !/^auto$/i.test(d.value) && !/:hover|:focus|:active|\.is-|\[data-|\[aria-|\.open|\.active|\.animating/.test(selectorOf(d.stack))) {
        add("will-change", d.line, `${d.prop}: ${d.value}`);
      }
      if (!TIMING_PROPS.has(d.prop) || inReduce(d.stack)) continue;
      const selector = selectorOf(d.stack);
      const guarded = globalRule || inNoPreference(d.stack) || (hasReduceBlock && covered(selector, d.prop, d.value));
      checkTiming(d.prop, d.value, d.line, guarded);
      if (!guarded && movesWithCustomTiming(d.prop, d.value)) {
        if (hasReduceBlock) add("no-reduced-motion", d.line, `${selector} { ${d.prop}: ${d.value} }`, "this file's reduced-motion block doesn't reach this rule");
        else {
          unguardedCount++;
          unguarded ??= { line: d.line, snippet: `${selector} { ${d.prop}: ${d.value} }` };
        }
      }
    }
    if (unguarded) add("no-reduced-motion", unguarded.line, unguarded.snippet, `no reduced-motion block in this file; ${unguardedCount} declaration(s) affected`);
    for (const b of css.blocks) {
      const name = keyframesName(b.prelude);
      if (!name) continue;
      const others = (project.keyframes.get(name) ?? []).filter((k) => !(k.file === file && k.line === b.line));
      if (others.length && project.keyframes.get(name)?.some((k) => k.file === file)) {
        add("dup-keyframes", b.line, b.prelude, `also at ${others.map((o) => `${relTo(project.root, o.file)}:${o.line}`).join(", ")}`);
      }
    }
  }

  if (!JS_EXT.test(file) && !MARKUP_EXT.test(file)) return hits;
  if (TEST_FILE.test(toPosix(file))) return hits;
  const starts = lineStarts(text);
  const at = (index) => lineAt(starts, index);
  const lineOf = (index) => lines[at(index) - 1];
  const reduceCheck = JS_REDUCE_CHECK.test(text);

  if (MARKUP_EXT.test(file)) {
    for (const m of text.matchAll(/\sstyle\s*=\s*"([^"]*)"/gi)) {
      const line = at(m.index);
      if (ignored(line)) continue;
      for (const part of m[1].split(";")) {
        const [prop, ...rest] = part.split(":");
        const name = prop?.trim().toLowerCase();
        if (name && TIMING_PROPS.has(name)) checkTiming(name, rest.join(":").trim(), line, globalRule);
      }
    }
  }

  const seen = new Set();
  for (const { re, loop } of PER_FRAME) {
    for (const m of text.matchAll(re)) {
      const body = callbackBody(text, m.index + m[0].length);
      if (loop && !/requestAnimationFrame\(/.test(body)) continue;
      const setters = [...new Set([...body.matchAll(SETTER)].map((s) => s[1]).filter((s) => !NOT_STATE.has(s)))];
      const line = at(m.index);
      if (setters.length && !seen.has(line) && !ignored(line)) {
        seen.add(line);
        add("state-per-frame", line, lines[line - 1], `calls ${setters.join(", ")}`);
      }
    }
  }

  // A one-off next-frame call (focus, measure) is fine; only a callback that schedules itself animates.
  const rafLoop = !reduceCheck && [...text.matchAll(/\brequestAnimationFrame\(/g)].find((m) => /requestAnimationFrame\(/.test(callbackBody(text, m.index + m[0].length)));
  if (rafLoop && !ignored(at(rafLoop.index))) add("raf-no-guard", at(rafLoop.index), lineOf(rafLoop.index), "a loop that runs whatever the reduced-motion setting; fine only if it shows live data (playback, a meter)");
  const waapi = text.search(/\.animate\(/);
  if (waapi !== -1 && !reduceCheck && !ignored(at(waapi))) add("animate-no-guard", at(waapi), lineOf(waapi));

  for (const m of text.matchAll(/\b(repeat\s*:\s*(?:Infinity|-1)\b|iterations\s*:\s*Infinity\b|animation\s*:\s*["'`][^"'`]*\binfinite\b)/g)) {
    if (!ignored(at(m.index))) add("infinite", at(m.index), lineOf(m.index), reduceCheck ? "file has a reduced-motion check; confirm it covers this loop" : "no reduced-motion check in this file");
  }
  for (const m of text.matchAll(/<video\b[^>]*>/gis)) {
    if (/autoplay/i.test(m[0]) && /\bloop\b/i.test(m[0]) && !ignored(at(m.index))) {
      add("infinite", at(m.index), m[0], reduceCheck ? "looping video; check it pauses under reduced motion and off-screen" : "looping autoplay video with no reduced-motion check");
    }
  }

  for (const m of text.matchAll(/\b(transition|animation|transitionDuration|animationDuration|transitionTimingFunction)\s*:\s*(["'`])([^"'`\n]*)\2/g)) {
    const line = at(m.index);
    if (ignored(line)) continue;
    if (rawTimes(m[3]).length || rawEasings(m[3]).length) add("raw-timing", line, lines[line - 1], "inline style");
    if (m[1] === "transition" && /(^|,)\s*all\b/.test(m[3])) add("transition-all", line, lines[line - 1], "inline style");
  }

  for (const m of text.matchAll(/addEventListener\(\s*["'](wheel|touchstart|touchmove)["'][^;]{0,200}/g)) {
    if (!/passive/.test(m[0]) && !ignored(at(m.index))) add("passive-listener", at(m.index), lineOf(m.index));
  }

  if (project.usesTailwind) {
    for (const m of text.matchAll(/(?<![\w-])(?:[\w-]+:)*(duration|delay|ease)-\[[^\]\s]+\]/g)) {
      if (!ignored(at(m.index))) add("tw-arbitrary", at(m.index), m[0]);
    }
    if (!globalRule) {
      for (const m of text.matchAll(/(?<![\w/-])((?:[\w-]+:)*)animate-(?!none\b)[\w-]+(?:\[[^\]]*\])?/g)) {
        const line = at(m.index);
        if (/motion-safe:/.test(m[1]) || /motion-reduce:/.test(lines[line - 1]) || ignored(line)) continue;
        add("tw-animate-no-reduce", line, m[0]);
      }
    }
  }

  const reactMotion = text.match(/from\s+["'](?:motion\/react|motion\/react-client|framer-motion)["']/);
  if (reactMotion && !project.motionConfig.length && !/\buseReducedMotion\(/.test(text) && !ignored(at(reactMotion.index))) {
    add("motion-no-config", at(reactMotion.index), lineOf(reactMotion.index));
  }
  const vanillaMotion = text.match(/from\s+["']motion["']/);
  if (vanillaMotion && !reduceCheck && /\banimate\(/.test(text) && !ignored(at(vanillaMotion.index))) {
    add("no-reduced-motion", at(vanillaMotion.index), lineOf(vanillaMotion.index), "motion animate() with no reduced-motion check in this file");
  }

  const gsapCall = text.match(/\bgsap\.(?:to|from|fromTo|timeline|set)\(/);
  if (gsapCall && !ignored(at(gsapCall.index))) {
    if (/\.(jsx|tsx)$/i.test(file) && !/useGSAP|gsap\.context|\.revert\(\)|\.kill\(\)/.test(text)) add("gsap-no-cleanup", at(gsapCall.index), lineOf(gsapCall.index));
    if (!reduceCheck) add("no-reduced-motion", at(gsapCall.index), lineOf(gsapCall.index), "GSAP tween with no reduced-motion check (gsap.matchMedia with a reduce condition, or a hook)");
  }

  if (/from\s+["'](?:motion|motion\/react|framer-motion|gsap|animejs)["']|\.animate\(/.test(text)) {
    const literals = [...text.matchAll(/\b(duration|delay|stagger)\s*:\s*\d*\.?\d+\b|\bease\s*:\s*\[\s*[\d.]/g)];
    if (literals.length >= 2) add("js-timing", at(literals[0].index), lineOf(literals[0].index), `${literals.length} timing literals in this file`);
  }

  return hits;
}

export function audit(root, paths) {
  const project = scanProject(root);
  const { files, note } = targetFiles(root, paths);
  const hits = [];
  for (const file of files) {
    const text = project.texts.get(file) ?? read(file);
    if (text !== null) hits.push(...auditFile(file, text, project));
  }
  const order = { must: 0, should: 1, consider: 2 };
  hits.sort((a, b) => order[a.severity] - order[b.severity] || a.rule.localeCompare(b.rule) || a.file.localeCompare(b.file) || a.line - b.line);
  const context = {
    tokens: project.tokens.length ? [...new Set(project.tokens.map((t) => prefixOf(t.prop)))].slice(0, 6).join(", ") : "none",
    reducedMotion: project.globalRules.length ? "global rule" : project.reducing.size ? `token override (${[...project.reducing].join(", ")})` : "per file",
  };
  return { root: toPosix(root), note, files: files.length, context, hits };
}

// `limit` keeps a legacy stylesheet with hundreds of hits from flooding the reader; --all lifts it.
function printAudit(r, limit) {
  const out = [`# Motion audit candidates: ${r.root}`, "", `${r.note} Tokens: ${r.context.tokens}. Reduced motion: ${r.context.reducedMotion}.`];
  out.push("Every hit is a candidate. Read the line in context before reporting it, and drop false positives.");
  const titles = { must: "Must fix", should: "Should fix", consider: "Consider" };
  for (const severity of ["must", "should", "consider"]) {
    const group = r.hits.filter((h) => h.severity === severity);
    if (!group.length) continue;
    out.push("", `## ${titles[severity]} (${group.length})`);
    for (const rule of [...new Set(group.map((h) => h.rule))]) {
      const hits = group.filter((h) => h.rule === rule);
      out.push("", `### ${rule} (${hits.length}): ${RULE_TEXT[rule]}`);
      for (const h of hits.slice(0, limit)) out.push(`- ${h.file}:${h.line}  ${h.snippet}${h.note ? `  [${h.note}]` : ""}`);
      if (hits.length > limit) {
        const perFile = new Map();
        for (const h of hits.slice(limit)) perFile.set(h.file, (perFile.get(h.file) ?? 0) + 1);
        const top = [...perFile].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([f, n]) => `${f} (${n})`);
        out.push(`- … ${hits.length - limit} more: ${top.join(", ")}${perFile.size > 6 ? ", …" : ""}. Narrow the path or pass --all to list them.`);
      }
    }
  }
  const count = (s) => r.hits.filter((h) => h.severity === s).length;
  out.push("", `Totals: must ${count("must")}, should ${count("should")}, consider ${count("consider")}.`);
  return out.join("\n");
}

// The nearest folder up from `dir` with a package.json, so running from src/ still sees the whole project.
function findRoot(dir) {
  for (let d = dir; ; d = path.dirname(d)) {
    if (existsSync(path.join(d, "package.json"))) return d;
    if (path.dirname(d) === d) return dir;
  }
}

function main(argv) {
  const [command, ...rest] = argv;
  const json = rest.includes("--json");
  const all = rest.includes("--all");
  const args = rest.filter((a) => a !== "--json" && a !== "--all");
  const rootFlag = args.indexOf("--root");
  let root = findRoot(process.cwd());
  if (rootFlag !== -1) {
    root = path.resolve(args[rootFlag + 1] ?? ".");
    args.splice(rootFlag, 2);
  }

  if (command === "profile") {
    if (args[0]) root = path.resolve(args[0]);
    const summary = summarizeProfile(scanProject(root));
    process.stdout.write((json ? JSON.stringify(summary, null, 2) : printProfile(summary)) + "\n");
  } else if (command === "audit") {
    const result = audit(root, args);
    process.stdout.write((json ? JSON.stringify(result, null, 2) : printAudit(result, all ? Infinity : 20)) + "\n");
  } else {
    process.stdout.write(USAGE + "\n");
    process.exitCode = command ? 1 : 0;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) main(process.argv.slice(2));
