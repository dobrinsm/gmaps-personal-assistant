/**
 * Frontend security & XSS regression tests (Node, no browser needed).
 * Validates F-01 from the 2026-08-30 production audit: agent text rendered
 * through the chat markdown path must never inject live markup.
 *
 * Run: node tests/test_frontend_security.js
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const src = fs.readFileSync(path.join(__dirname, "..", "frontend", "app.js"), "utf8");

function makeEl(id) {
  return {
    id, innerHTML: "", textContent: "", value: "", disabled: false,
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {}, getAttribute() { return null; },
    appendChild() {}, addEventListener() {}, removeEventListener() {},
    style: {}, scrollIntoView() {}, querySelectorAll() { return []; },
  };
}
const elements = {};
const sandbox = {
  window: { location: { origin: "http://localhost:3000" }, open() {}, addEventListener() {} },
  document: {
    getElementById(id) { if (!elements[id]) elements[id] = makeEl(id); return elements[id]; },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    createElement(tag) { return makeEl(`created-${tag}`); },
    addEventListener() {},
    body: { appendChild() {}, removeChild() {} },
  },
  localStorage: {
    _s: {}, getItem(k) { return this._s[k] || null; },
    setItem(k, v) { this._s[k] = String(v); },
  },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  alert() {}, confirm() { return false; },
  console,
  Blob: class {}, URL: { createObjectURL() { return "blob:x"; }, revokeObjectURL() {} },
  setTimeout, clearTimeout,
  L: undefined,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(src, sandbox, { filename: "app.js" });

let passed = 0, failed = 0;
function check(name, cond) {
  if (cond) { passed++; }
  else { failed++; console.error(`FAIL: ${name}`); }
}

// ── F-01: markedParse must escape HTML before applying markdown ──────
const probes = [
  '<img src=x onerror=window.__xss=1>',
  '<svg onload=alert(1)>',
  '<script>alert(1)</script>',
  '"><img src=x onerror=alert(1)>',
  "Osteria <b>da Vito</b> & 'friends'",
  '<iframe src="javascript:alert(1)">',
];
for (const probe of probes) {
  const out = vm.runInContext(`markedParse(${JSON.stringify(probe)})`, sandbox);
  check(
    `markedParse output has no live <img/<svg/<script/<iframe tags (${probe.slice(0, 22)}…)`,
    !/<(img|svg|script|iframe)\b/i.test(out)
  );
  check(
    `markedParse output is escaped text for probe (${probe.slice(0, 22)}…)`,
    out.includes("&lt;") || !/[<>]/.test(out)
  );
}

// Markdown features still work on benign text (backward compatibility).
check("bold still renders", vm.runInContext(`markedParse('**hello**')`, sandbox).includes("<strong>hello</strong>"));
check("italic still renders", vm.runInContext(`markedParse('*hi*')`, sandbox).includes("<em>hi</em>"));
check("paragraph breaks survive", vm.runInContext(`markedParse('a\\n\\nb')`, sandbox).includes("</p><p>"));
check("single newlines become <br>", vm.runInContext(`markedParse('a\\nb')`, sandbox).includes("<br>"));
check("plain text untouched", vm.runInContext(`markedParse('hello world')`, sandbox) === "hello world");
check("markdown inside injected markup is inert",
  vm.runInContext(`markedParse('**<img src=x>**')`, sandbox).includes("&lt;img"));

// Original audit probe must now be inert end-to-end.
const auditProbe = '<img src=x onerror=window.__xss=1>';
const rendered = vm.runInContext(`markedParse(${JSON.stringify(auditProbe)})`, sandbox);
check("audit probe <img src=x onerror=...> is escaped (renders as text)", rendered.includes("&lt;img"));
check("audit probe does not contain raw '<img'", !rendered.includes("<img"));

// Place-card HTML still escapes names (regression check on escapeHtml usage).
check("escapeHtml escapes angle brackets", vm.runInContext(`escapeHtml('<x>')`, sandbox) === "&lt;x&gt;");
check("escapeHtml escapes quotes", vm.runInContext(`escapeHtml('"')`, sandbox).includes("&quot;"));

// Feedback onclick must no longer embed a raw double-stringified JSON blob
// in an HTML attribute (F-02 root cause guard at the string-template level).
check("app.js no longer builds inline onclick sendFeedback handlers",
  !src.includes("onclick=\\\"sendFeedback"));
check("app.js no longer double-stringifies place JSON into attributes",
  !src.includes("JSON.stringify(JSON.stringify"));

console.log(`\nFrontend security: ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
