# Remediation Triage — gmaps-personal-assistant

**Source report:** `docs/user-testing-report.md` + `docs/friction-backlog.md` (production audit, 2026-08-30)
**Triage date:** 2026-08-30 · **Codebase state:** `main` @ 2135e5c (clean tree)
**Method:** every finding re-verified against current code; frontend defects additionally reproduced in a
mock-server browser harness (headless Chromium, 68 pytest + 27 node export-smoke passing before changes).

| Finding ID | Classification | Reproducible | Root cause | Severity | Frequency | User impact | Security impact | Effort | Fix in this run | Evidence |
|------------|----------------|--------------|------------|----------|-----------|-------------|-----------------|--------|------------------|----------|
| F-01 | Security concern (confirmed defect) | ✅ (browser probe + code) | `markedParse()` output injected via `innerHTML` without escaping (app.js:328, 486–492); model output is attacker-influenced text | S4 | F3 | Script execution in any visitor's browser; identity/notebook hijack | **High** — stored XSS via model output | S | **YES** | Reproduced: `<img src=x onerror>` executed; DOM contained raw element; code path confirmed |
| F-02 | Confirmed defect (core journey dead) | ✅ (browser + code) | app.js:312–314 build `onclick="sendFeedback('…', '…', 'like', ${JSON.stringify(JSON.stringify(obj))})"` — the double-stringified JSON begins with `"` which terminates the HTML attribute, leaving a truncated JS call | S4 | F4 | Feedback loop never fires; headline feature dead; silent failure (no toast) | None beyond broken trust | S | **YES** | Console SyntaxError + missing network call + malformed attribute read from live DOM; code confirmed |
| F-03 | Confirmed defect (data-loss perception) | ✅ | Chat is client-side only; backend already persists messages in the session doc (`agent.py:310–318`, `db.py:88–110`) but frontend never replays them | S3 | F4 | Users lose conversation mid-trip; context gone | None | M | **YES** (frontend replay) | Before/after reload counts (5→1) in prod test; backend persistence confirmed in code |
| F-04 | Confirmed performance/reliability issue | ✅ (timing) | Synchronous Places→LLM pipeline (+likely Cloud Run cold start); no streaming | S3 | F4 | First impression feels frozen; abandonment risk | None | L | No — deferred | Network timings 30.4s/8.4s/~9s; static spinner |
| F-04a | Confirmed UX friction (partial F-04 mitigation, frontend-only) | ✅ | Chat submit handler never disables input; `chatInput.value=''` runs synchronously so button double-click is accidentally safe, but double **Enter**/programmatic submits race | S2 | F3 | Duplicate LLM calls; confusing double responses | Cost/quota risk | S | **YES** (send-lock) | Double chip-click produced two user messages + two agent calls |
| F-05 | Confirmed UX friction | ✅ (375px emulation + code: zero `@media` rules) | `.workspace` fixed 2-pane flex; no responsive CSS | S3 | F4 | Mobile web unusable — notebook 28px sliver | None | M | **YES** (breakpoint; scoped to readability) | Measured pane widths; screenshot; grep |
| F-06 | Confirmed UX friction | ✅ (CDP dialog handling required) | `alert()` for upload result/errors, `confirm()` for reset (app.js:458,463,468,473) | S2 | F3 | Page freeze; unfriendly raw error copy | None | S | **YES** (in-app modal + toast infra already present) | Live capture of blocking dialog + alert copy |
| F-07 | Confirmed UX friction | ✅ (fresh localStorage → defaults styled as learned) | `get_user_profile()` fabricates a full default profile for unknown ids; frontend renders it identically to a real one | S2 | F4 | False mental model ("system already knows me") | Minor trust issue | S–M | **YES** (flag + empty-state UI) | Fresh-visitor observation + `db.py:33–53` |
| F-08 | Confirmed UX friction (trust/copy) | ✅ | Static "Active" pill; unconditional "Gemini will analyze" copy | S2 | F3 | Trust erosion | None | S | **YES** (copy-level only) | DOM + code |
| F-09 | Confirmed UX friction | ✅ | `price_level` raw enum passthrough; not shown on cards | S2 | F3 | Unpolished exports; missing context | None | S | **YES** (humanize enum in exports + card chip) | Export contents |
| F-10 | Confirmed UX friction | ✅ (offline sim) | No retry affordance; input cleared on failure; misleading offline copy | S2 | F3 | Lost turns; confusion | None | S | **YES** (retry + input restore + copy) | Offline repro |
| F-11 | Confirmed UX friction (product gap) | ✅ (counts 0→3→6→9→12; `agent.py:286` auto-append) | Server auto-appends; no curation UI | S2 | F3 | Polluted itinerary; no remove | None | M–L | No — feature request, deferred | Observed counts |
| F-12 | Feature request | ✅ (absence verified) | No share functionality exists | S2 | F4 | Stated workflow unsupported | None | L | No — feature request | 404 probes |
| F-13 | Not reproducible from repo (environment/config) | ⚠️ prod-only; **not reproducible locally** | CARTO tile entitlement/referer (hypothesis) | S2 | F4 | Map basemap watermark | None | S | No — **production config, not code**; needs owner action | Tile entries status 0; locally identical code renders fine |
| F-14 | Confirmed UX friction | ✅ | Click-to-prefill overwrites typed input (app.js:342–345) | S2 | F3 | Friction in core loop | None | S | **YES** (non-destructive prefill) | Browser interaction |
| F-15 | Confirmed UX friction | ✅ | Single mixed-destination shortlist; no per-city segmentation | S2 | F2 | Useless exports across cities | None | L | No — structural (deferred with F-11) | zoom 4; mixed directions URL |
| F-16 | Confirmed accessibility issue | ✅ (heuristic + DOM audit) | No aria labels/live regions, unlabeled inputs, emoji-only buttons, no Escape handling, 3.04:1 hint text, non-focusable clarification items/dropzone | S2 practical | F4 | SR/keyboard users blocked from core flows | None | M | **YES** (targeted subset: labels, roles, live regions, Escape, focusability, contrast vars) | AX audit + computed contrast |
| F-17 | Confirmed UX friction (copy) | ✅ | Raw internal keys in preference chips (`fancy_level: nothing fancy`) | S1 | F3 | Confusing | None | S | **YES** | Screenshot/DOM |
| F-18 | Confirmed UX friction (docs/onboarding) | ✅ | Upload modal lacks Takeout how-to (app.js modal copy) | S1 | F2 | Dead-end for non-technical users | None | S | **YES** | Modal copy |
| F-19 | Confirmed UX friction (minor) | ✅ | Hint says "notebook order"; KML/CSV sort by score | S1 | F2 | Export order surprise | None | S | **YES** (copy aligns code) | Code + copy |
| F-20 | Hypothesis requiring more evidence (minor) | ✅ observed acceptance; no failure observed | No maxlength on chat input | S1 | F2 | Potential timeouts/cost on huge inputs | Low | S | **YES** (5k soft cap — smallest safe constraint) | Boundary test |
| F-21 | Confirmed defect (cosmetic) | ✅ | `nbLearned` renders an empty bordered section | S1 | F2 | Cosmetic noise | None | S | **YES** (hidden when empty) | DOM measurement |
| F-22 | Confirmed defect (polish) | ✅ | No favicon defined | S0 | F3 | Minor polish | None | S | **YES** (inline SVG data-URI favicon) | Tab icon |

## Explicitly deferred (with reasons)

- **F-04 (latency/streaming)** — Effort L: SSE streaming + `collaborate()` rework. Rejected for this batch (risk of destabilizing the agent loop in a single session). Interim mitigation shipped instead: staged, rotating status text (see F-08 work) so waits feel intentional. **Next action:** backend streaming + Cloud Run `min-instances=1`. Priority P1.
- **F-11 auto-shortlist / curation UI** — Feature work (data model + UI for save/remove/reorder), not a defect fix. **Next action:** product spec; explicit "save to itinerary" + remove control. Priority P2.
- **F-12 share links** — Feature request; needs Firestore-backed read-only tokens. Out of scope. Priority P2.
- **F-15 per-destination itineraries** — Depends on F-11's data-model work. Deferred with it. Priority P2.
- **F-13 map tiles** — **Not a code defect**: CARTO basemap entitlement/referer is deployment configuration. Fix belongs to infrastructure (register the Cloud Run URL with CARTO or use entitled tiles). Documented in release notes as a deploy-time action item. Priority P1, owner: infra.
- **F-04-partial (spinner text)** handled via F-08 copy; full streaming deferred.

## Findings requiring human research
- Whether 31s tolerance causes abandonment (needs analytics), comprehension of dual scores, trust in auto-curated shortlist — documented in the original report §12; no code action in this batch.
