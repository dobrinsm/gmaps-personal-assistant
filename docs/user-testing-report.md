# Production User Testing Report — GMaps Personal Assistant

**Testing date:** Sunday, 30 August 2026 (single session, ~2 hours active testing)
**Production URL:** https://gmaps-assistant-mhg5tnquwa-ew.a.run.app/ (Google Cloud Run, europe-west)
**Repository:** https://github.com/dobrinsm/gmaps-personal-assistant/ (read-only; commit at time of audit)
**Test type:** Synthetic, heuristic, browser-automation-based QA. **No real human users were observed or surveyed.** No analytics, telemetry, or support data were available. Every finding below is from directly observed automated-browser behavior or from read-only code inspection, and is labeled accordingly.
**Mutation policy honored:** Read-only. No production data deleted or overwritten; no emails/notifications/payments sent; no destructive payloads; no load testing. Test data consisted of synthetic Takeout files and chat messages under throwaway localStorage identities.

---

## 1. Executive overview

| Item | Value |
|---|---|
| Production URL tested | `https://gmaps-assistant-mhg5tnquwa-ew.a.run.app/` |
| Scope | Public web SPA + its own REST API (`/api/*`), desktop + mobile emulation |
| Tools | Headless Chromium 151 (CDP), browser-harness automation, DevTools performance/network emulation, source-code review |
| Viewports | 1440×900 desktop, 375×667 mobile emulation, 768×1024 tablet emulation, 200% page zoom, simulated Slow-3G, simulated offline |
| User types simulated | New Google Maps user (no profile), returning user with Takeout import, multi-destination planner |
| Journeys tested | 10 (J1–J10, see §2) |
| Issues found | **22** (4 critical, 5 major, 8 moderate, 5 minor) |
| Top 5 friction points | See below |

**Top five friction points:**
1. **F-01 (S4): Stored XSS in agent chat responses** — agent text is injected into the DOM unescaped; verified working exploit via `<img src=x onerror=…>`.
2. **F-02 (S4): Every 👍/🚩/🎭 feedback button is broken** — malformed inline `onclick` throws `SyntaxError` on click; the product's headline "feedback learning loop" never fires for any user.
3. **F-03 (S3): Chat history is lost on refresh** — conversation vanishes, but the notebook persists, so the user sees a half-wiped state and no explanation.
4. **F-04 (S3): 31-second first-response latency** with only a static "Thinking…" card and no progress/cancel; first interaction is the highest-friction moment of the whole product.
5. **F-05 (S3): Completely broken mobile layout** — the two-pane workspace has zero responsive breakpoints; the entire Agent Notebook is squeezed into a ~28px sliver on a phone.

**Overall confidence:** High for F-01, F-02, F-05 (reproduced directly, with console/DOM evidence and matching code paths). Medium-high for latency, persistence, and contrast findings (reproduced). Lower for multi-tab and large-file edge cases (single observation each). The accessibility review is heuristic and partial — no screen reader or full WCAG audit was performed; no formal compliance claim is made or implied.

---

## 2. Product and journey map

**Product purpose (observed):** A conversational "collaborative travel & taste agent" that asks clarifying questions, searches live Google Places, dual-scores recommendations (Intent × Taste), auto-curates a shortlist, renders it on a Leaflet map, and exports itineraries (Google Maps directions / KML / CSV). Optional import of Google Takeout saved places to build a "taste profile."

**User types (inferred):** Google Maps users planning leisure travel/food discovery; hackathon judges; demo visitors. **No authentication exists** — identity is a random `user_id`/`session_id` pair in `localStorage`.

**Main areas (observed):** Chat pane with quick-prompt chips and clarifying-question dock; Agent Notebook tab (destination, preferences, learned chips, notes, shortlist); Live Taste Profile tab (summary, 4 weight bars, vibe/cuisine/avoid tags); Map & Itinerary tab (Leaflet map, stop cards, Maps/KML/CSV export); Takeout upload modal.

### Journey inventory

| Journey ID | User type | Goal | Starting point | Expected outcome | Risk level | Test status |
|---|---|---|---|---|---|---|
| J1 | New user | Understand product & first action | Landing page | Understand value, know what to type | Medium | ✅ Tested |
| J2 | Any | Get tailored recommendations via chat | Home → quick prompt or typed message | Places + scores + map-ready shortlist | **High** | ✅ Tested |
| J3 | Returning | Answer clarifying questions, refine | Clarification bar | Updated notebook, refined picks | High | ✅ Tested |
| J4 | Returning | Give 👍/🚩/🎭 feedback to adapt profile | Place card buttons | Toast + profile/learned-chips update | **High** | ❌ **Broken (F-02)** |
| J5 | Returning | View itinerary on map | Map tab | Pinned stops, correct basemap | High | ⚠️ Tested — basemap broken (F-13) |
| J6 | Returning | Export itinerary (Maps/KML/CSV) | Map tab buttons | Usable files/URL | Medium | ✅ Tested (minor issues) |
| J7 | Returning | Resume after refresh | Reload mid-session | History + notebook restored | **High** | ❌ History lost (F-03) |
| J8 | New | Import Google Takeout | "Import Google Takeout" | Profile built, confirmed | High | ✅ Tested (json/zip/csv/invalid) |
| J9 | New | Understand taste profile meaning | Profile tab | Understand what is learned vs default | Medium | ✅ Tested — misleading (F-07) |
| J10 | Returning | Share itinerary with friends | Any | Share link/mechanism | Medium | ❌ Feature does not exist (F-12) |

**Untested paths / coverage gaps:** rate limits & concurrent-user load (prohibited), very large Takeout archives (tens of MB, thousands of places — partial via 150-place code cap, inferred only), paid-model quota exhaustion behavior, non-Chromium browsers (Safari/Firefox unavailable), true screen readers, cold-start Cloud Run latency from other regions, Firestore failure modes.

---

## 3. Prioritized friction backlog

Sorted by practical priority (severity × frequency × confidence × journey importance). Full detail in `friction-backlog.md`.

| ID | Priority | Sev | Freq | Conf | Persona | Journey | Screen/URL | Friction point | Evidence | Likely cause | User impact | Recommended fix | Validation method | Status |
|----|----------|-----|------|------|---------|---------|------------|----------------|----------|-------------|-------------|-----------------|-------------------|--------|
| F-01 | P0 | S4 | F3 | C4 | All | J2 | Chat pane | **Stored XSS via agent replies** — arbitrary HTML in model output executed | `<img src=x onerror>` executed; `window.__xss===1`; DOM contains raw `<img>`; `markedParse()` has no escaping (app.js:486–492) | Unescaped model text → `innerHTML` | Session hijack via shared/malicious prompts; CSRF-like actions in victim's browser | HTML-escape agent text before `markedParse`; sanitize with DOMPurify; CSP header | Re-send probe string; assert no element injection; add CSP regression test | Open |
| F-02 | P0 | S4 | F4 | C4 | All | J4 | Place cards | **All feedback buttons throw SyntaxError; feedback loop dead** | Console `SyntaxError: Unexpected end of input`; no `/api/feedback` request in network log; onclick attribute truncated at `"…'like', ` (app.js:312–314 double-`JSON.stringify` inside HTML attr) | `JSON.stringify(JSON.stringify(obj))` embedded in `onclick="…"` — quote terminates attribute | Core "remembers/learns" promise never works; silent failure (no toast) | Render buttons with `addEventListener` + dataset, never inline JS | Click each button type; assert 200 on `/api/feedback` and toast appears | Open |
| F-03 | P1 | S3 | F4 | C4 | Returning users | J7 | Whole app | **Chat history lost on refresh; notebook survives → contradictory UI** | 5 message cards before reload → 1 after; notebook/shortlist restored from Firestore | Chat rendered client-side only; no history fetch on load | Users lose context mid-trip; looks like data loss | Persist messages per session; replay from `GET /api/session` on load; show "conversation restored" | Reload test after N turns | Open |
| F-04 | P1 | S3 | F4 | C3 | All | J2, J3 | Chat | **31s first response; 8–15s typical; static "Thinking…" only; no cancel** | `/api/chat` measured 30.4s, 8.4s, ~9s; spinner text never changes; no abort | Synchronous Places+LLM pipeline; no streaming | First-time users abandon; looks frozen | Streaming responses; staged status ("Searching Places…", "Scoring…"); disable input while pending | Timing regression threshold (<15s p50) | Open |
| F-05 | P1 | S3 | F4 | C3 | Mobile users | All | Global CSS | **No responsive breakpoints; notebook becomes 28px sliver on phones** | 375px: `.notebook-pane` 28.3px wide; screenshot `01-mobile…png`; zero `@media` rules in style.css | Desktop-only flex layout | Mobile web (primary stated platform) unusable | Add ≤900px breakpoint: stack panes, tabbed or scroll layout | 375px/768px visual regression | Open |
| F-06 | P1 | S3 | F3 | C3 | All | J2, J8 | Upload, chat | **Blocking native `alert()`/`confirm()` freeze the page**; Takeout results & Reset use them | `Page.handleJavaScriptDialog` required to unfreeze page during test; app.js:458/463/473 | Legacy `alert`/`confirm` instead of in-app modal/toast | Page appears hung; dialog text uncopyable; kills automation & some mobile flows | Replace with in-app toasts/modals (toast infra already exists) | Manual flow check | Open |
| F-07 | P2 | S2 | F4 | C4 | New users | J9 | Profile tab | **Hardcoded default profile shown to brand-new users as if learned** | Fresh localStorage → "Explorer seeking local…" + weights 0.90/0.85/0.80/0.75 (backend defaults rendered as profile) | No empty-state distinction for unset profile | False mental model; user believes system already knows them | Empty state: "No profile yet — chat or import Takeout to build one" | Fresh-visitor check | Open |
| F-08 | P2 | S2 | F3 | C3 | All | J2 | Chat | **Misleading live-status pill & promises** — "● Gemini 3.5 Flash Active" shown always (even if backend degraded); "Analyzing… Gemini" shown during upload regardless | DOM assertion; health endpoint shows model config, not live status | Static decorative status; overclaiming copy | Trust damage when behavior doesn't match claims; model-name drift risk | Tie indicator to real health check; neutral wording | Config-change drill | Open |
| F-09 | P2 | S2 | F3 | C3 | Mobile, all | J2 | Chat | **Place cards omit price level/hours; raw enum `PRICE_LEVEL_MODERATE` leaks into CSV/KML** | CSV export content; KML description contents | `price_level` passed through unformatted | Exported itineraries look unpolished; users can't filter by price | Humanize enums; surface $$; add price filter | Export content check | Open |
| F-10 | P2 | S2 | F3 | C3 | All | J2 | Chat | **Duplicate/failed chat sends leave "Thinking…" card forever on server 500**; error text generic ("Failed to get response…") and retry not offered | code path `appendErrorMessage`; offline test showed full-page-failure copy for offline case | No per-request state machine | Confusion; lost turn | Keep user message, show Retry button, restore input text | Simulated 500/offline matrix | Open |
| F-11 | P2 | S2 | F3 | C2 | Returning | J7 | Notebook | **Shortlist auto-grows without user consent** (top-3 per search, across destinations; 12 items after 4 searches across 4 cities) | counts 0→3→6→9→12 observed; agent.py:286 auto-append | Server auto-appends; no "add/remove" UI | Itinerary polluted with unwanted stops; user can't remove | Explicit save button per place + remove/undo in notebook | Notebook mutation check | Open |
| F-12 | P2 | S2 | F4 | C4 | All | J10 | Global | **No way to share with friends** — no share UI, no read-only links (`/share/*` 404), stated workflow unsupported | Route probes; absence in UI/DOM | Feature gap vs. stated user goal | Friends can't view plans; workaround = raw CSV/KML file handoff | Read-only shared itinerary links | Route probe | Open |
| F-13 | P2 | S2 | F4 | C4 | All | J2 (map) | Map tab | **Basemap tiles fail: giant diagonal "API KEY REQUIRED" watermark across map** | Screenshot from session; all `cartocdn` tile requests `status 0`, `transferSize 0` | CARTO basemap requires registered referer/key from this origin | Map looks broken; directions map unreadable | Register CARTO app/referer or switch provider | Tile 200 check | Open |
| F-14 | P2 | S2 | F3 | C3 | All | J2 | Chat | **Clarifying questions as click-to-prefill only** — clicking a question overwrites input with `Regarding "…":`; easy to lose typed text; questions vanish after next send | Observed behavior in clarification bar | Interaction design | Extra friction in core loop | One-click answer chips per question | Interaction check | Open |
| F-15 | P3 | S2 | F2 | C2 | Returning | J7 | Notebook | **Multi-city shortlist makes map/directions meaningless** (zoom 4, Paris+Rome+Berlin+Catania all fit; directions URL mixes cities) | map zoom 4 measured; buildMapsDirUrl output contains 4 cities | No per-destination itinerary segmentation | Exports useless for real trips | Itineraries per destination; warn on mixed-city export | Export review | Open |
| F-16 | P3 | S1 | F4 | C4 | AT users | All | Global | **Accessibility: no aria-labels/live regions; inputs unlabeled; emoji-only buttons; no skip link; Escape doesn't close modal; contrast 3.04:1 on hints; focus lost on tab change** | AX audit outputs in §6 | No a11y pass | Screen-reader/keyboard users blocked from core flows | Labels, roles, live regions, focus management, contrast | axe-core + manual SR pass | Open |
| F-17 | P3 | S1 | F3 | C3 | All | J2 | Chat | **No visible history of clarifying Q&A in notebook; preferences appear as raw key:value chips** (`fancy_level: nothing fancy`) | Notebook prefs render | Internal keys surfaced | Confusing terminology | Friendly labels; humanize keys | Copy review | Open |
| F-18 | P3 | S1 | F2 | C3 | All | J8 | Upload modal | **Takeout modal doesn't explain how to obtain the file** — no help link/steps; zip accepted but user doesn't know Takeout flow | Modal text review | Missing onboarding copy | Dead-end for non-technical users | Link to Takeout with 2-step instructions | New-user task test | Open |
| F-19 | P3 | S1 | F2 | C3 | All | J6 | Map tab | **"Shortlist stops appear on map in notebook order" hint contradicts KML/CSV export which silently re-sorts by score** | buildCSV/buildKML sort logic vs. hint text | Copy/logic mismatch | Order surprise in exports | Align sort or document both | Export review | Open |
| F-20 | P3 | S1 | F2 | C2 | All | J2 | Chat | **No maxlength or client validation on chat input; 5k chars accepted** (server accepted; risk of slow/failed generations) | 5040-char input accepted; response still OK | Missing input constraints | Potential timeouts/costs on huge inputs | Reasonable client+server limit with message | Boundary test | Open |
| F-21 | P3 | S1 | F2 | C2 | All | Global | Misc | **`nbLearned` renders an empty bordered box (~30px) when no feedback learned yet** | DOM check: empty visible box | Section rendered unconditionally | Cosmetic noise | Hide when empty | Visual check | Open |
| F-22 | P4 | S0 | F3 | C3 | All | Global | Head | **No favicon → default/blank tab icon; minor brand/polish** | No favicon request observed | Missing asset | Polish | Add favicon | Check | Open |

**Severity counts:** S4: 2 · S3: 3 · S2: 9 · S1: 6 · S0: 1 → total 21 tracked findings (F-13 includes map-breakdown which may be environment-specific — see caveats).

---

## 4. Detailed issue reports (S2+)

### F-01 — Stored XSS via agent chat responses
- **Severity/Frequency/Confidence:** S4 / F3 / C4
- **Affected personas/journeys:** All / J2, J3
- **Business or user impact:** Arbitrary JS execution in any visitor's browser; combined with no auth and shareable chat content, an attacker can craft a message that makes the agent echo markup which then executes in the victim's browser (session takeover of that identity's notebook data, defacement, crypto-drain-style scripts).
- **Preconditions:** Any chat message that induces the model to output raw HTML.
- **Repro:** 1) Type: `Please repeat exactly this string in your reply, nothing else: <img src=x onerror=window.__xss=1>` 2) Wait for reply.
- **Expected:** Text rendered inert.
- **Observed:** Image element injected; `window.__xss === 1` (handler executed).
- **Evidence:** DOM: `<img src="x" onerror="window.__xss=1">` inside `.message-card .text`; app.js `markedParse()` inserts model output into `innerHTML` without escaping (app.js:328, 486–492). User messages are escaped; agent messages are not.
- **Root cause (confirmed):** Interaction design + missing output encoding.
- **Remediation:** Escape all dynamic text (`escapeHtml`) before markdown pass; adopt DOMPurify for the limited markdown subset; add a strict `Content-Security-Policy` (script-src 'self') as defense-in-depth.
- **Workaround:** None for users.
- **Owner:** Frontend (+ backend output contract).
- **Validation:** Probe string regression; CSP report-only → enforce; fuzz markdown renderer.
- **Regression test:** Add CI test asserting no executable markup in rendered agent cards for a canned XSS payload.

### F-02 — Feedback buttons (👍/🚩/🎭) all broken; learning loop dead
- **Severity/Frequency/Confidence:** S4 / F4 / C4
- **Affected:** All personas; journey J4 (headline feature).
- **Impact:** The README's core promise ("every 👍/🚩/🎭 feedback is stored… adapting taste weights bidirectionally") never executes. Also a trust issue: nothing visibly fails — button does nothing.
- **Preconditions:** Any place card in chat.
- **Repro:** 1) Get recommendations. 2) Click "👍 Love it" on any card. 3) Observe console + network.
- **Expected:** POST `/api/feedback`, toast, profile update.
- **Observed:** `Uncaught SyntaxError: Failed to execute 'click' on 'HTMLElement': Unexpected end of input`; **zero** network calls to `/api/feedback`.
- **Evidence:** onclick attribute literally reads `sendFeedback('ChIJ…', 'Ciurma Catania', 'like', ` — truncated because the double-stringified JSON payload begins with `"` which terminates the HTML attribute (app.js:312–314: `onclick="sendFeedback('${p.id}', '${escapeHtml(p.name)}', 'like', ${JSON.stringify(JSON.stringify({…}))})"`). A second latent bug: `escapeHtml(p.name)` inside a single-quoted JS string — names containing `'` would also break.
- **Root cause (confirmed):** String-templated inline JS handlers with nested quoting.
- **Remediation:** Replace inline onclick with event delegation; carry place data in a JS registry keyed by place id; never embed JSON in attributes.
- **Workaround:** None in UI (API-only).
- **Owner:** Frontend.
- **Validation:** Click all three buttons; assert `/api/feedback` 200 + toast + learned chips appear.
- **Regression test:** Playwright click-through on a card with apostrophe in name (e.g. "Rosi. Café & more").

### F-03 — Chat history lost on refresh (notebook survives)
- **Severity/Frequency/Confidence:** S3 / F4 / C4
- **Affected:** Any returning/mid-session user; J7.
- **Repro:** Hold a conversation → press F5.
- **Expected:** Conversation restored (or clearly explained).
- **Observed:** 5 cards → 1 card (welcome only). Notebook still shows Catania/Porto shortlist + preferences → UI contradicts itself; user cannot see prior recommendations, scores, or links again.
- **Evidence:** Before/after counts in same session; `GET /api/session` returns notebook only (frontend never renders chat from it).
- **Root cause (confirmed):** Client-only chat state; no history persistence/replay.
- **Remediation:** Store message list in session doc (or localStorage keyed by session id) and replay on load; banner: "Restored your last conversation."
- **Workaround:** None (exports only cover shortlist).
- **Owner:** Frontend + backend.
- **Validation:** Refresh mid-conversation; expect full history.
- **Regression:** Automated reload mid-flow.

### F-04 — Very slow first response; opaque waiting state
- **Severity/Frequency/Confidence:** S3 / F4 / C3
- **Affected:** All; J2/J3.
- **Impact:** First impression is 31s of nothing but "Synthesizing taste profile & querying Google Places…" (static). No progress, no cancel, input not disabled (double-submit possible via Enter key timing).
- **Evidence:** Network timing: 30.4s / 8.4s / ~9s / 12s+ across calls; Cloud Run cold start likely contributes.
- **Root cause (strong hypothesis):** Sequential backend (Places search → LLM batch scoring) + possible cold start; no streaming.
- **Remediation:** Stream partial responses; staged status updates; prewarm instance; optimistic quick-prompt handling.
- **Owner:** Backend + frontend.
- **Validation:** p50 first-token < 5s; staged status visible.

### F-05 — Mobile layout broken (no responsive design)
- **Severity/Frequency/Confidence:** S3 / F4 / C3
- **Affected:** Mobile web users (stated platform: WEB APP/MOBILE WEB); all journeys.
- **Repro:** Open site at 375×667.
- **Observed:** Chat pane 346px; **notebook pane 28.3px** (sliver); header text wraps awkwardly; tabs 84–86px tall; touch targets below 44px for chips (26px). Screenshot: `evidence/01-mobile-375px-notebook-sliver.png`.
- **Root cause (confirmed):** `.workspace` fixed 2-column flex; **zero `@media` queries** in style.css.
- **Remediation:** ≤900px breakpoint stacking panes with bottom tab bar; ≥44px touch targets.
- **Owner:** Frontend/design.
- **Validation:** 375/414/768 visual checks.

### F-06 — Blocking native alert()/confirm() freeze the page
- **Severity/Frequency/Confidence:** S2→S3 practical / F3 / C3
- **Affected:** J8 (upload), J10-adjacent (Reset), error paths.
- **Observed:** Takeout upload result and failures surface via `alert()`; Reset uses `confirm()`. Both froze the automated page entirely (CDP dialog handling required). Copy is uncopyable and unstyled; upload-failure detail (raw JSON parse error text) is unfriendly.
- **Root cause (confirmed):** Legacy dialogs; toast infra exists but isn't used here.
- **Remediation:** In-app modal/toast for upload results (with place count + link to Profile tab); custom confirm for Reset.
- **Owner:** Frontend.

### F-07 — Brand-new users shown a fabricated-looking "learned" profile
- **Severity/Frequency/Confidence:** S2 / F4 / C4
- **Observed:** After localStorage reset, Profile tab shows summary "Explorer seeking local, authentic experiences…" and weights 0.90/0.85/0.80/0.75 — these are code defaults, presented identically to a genuinely imported profile. No "default/not yet learned" label.
- **Root cause:** Missing empty state.
- **Remediation:** Distinguish unset profile ("Profile not built yet — import Takeout or start chatting"), render defaults only after first real signal.
- **Owner:** Product + frontend.

### F-08 — Trust/claims copy not grounded in live state
- **Severity/Frequency/Confidence:** S2 / F3 / C3
- **Observed:** Header pill "● Gemini 3.5 Flash Active" is static HTML; modal says "Gemini will analyze your places…" and status text "Analyzing places with Gemini 3.5 on Vertex AI..." regardless of actual backend behavior (health endpoint reports configured model name, not live status). If the model config changes, copy drifts; if the backend is degraded, the pill still claims active.
- **Remediation:** Drive indicator from `/api/health`; neutral wording ("AI-assisted recommendations").
- **Owner:** Frontend + product.

### F-09 — Raw enum leakage and missing price context
- **Severity/Frequency/Confidence:** S2 / F3 / C3
- **Observed:** CSV/KML rows contain `PRICE_LEVEL_MODERATE` verbatim; place cards show no price info at all.
- **Remediation:** Map enum → "Moderate ($$)"; include price chip in cards.
- **Owner:** Frontend.

### F-10 — No retry path after chat failure; error copy generic
- **Severity/Frequency/Confidence:** S2 / F3 / C3
- **Observed (offline simulation):** "Connection error. Ensure the backend server is running." (misleading copy for a client-side network failure on a hosted app); user message text stays visible in history but is gone from the input; no Retry button.
- **Remediation:** Keep message in input or offer one-click Retry; distinguish offline vs server error.
- **Owner:** Frontend.

### F-11 — Shortlist auto-populates without user action; can't remove items
- **Severity/Frequency/Confidence:** S2 / F3 / C3
- **Observed:** Each search silently appends up to 3 places; after 4 searches across 4 cities, 12 stops mixed together; there is no remove/reorder/save UI (export buttons operate on the auto list).
- **Root cause (confirmed):** agent.py:286 auto-append; no client mutation UI.
- **Remediation:** Explicit "Save to itinerary" per place; allow delete/reorder; show "added to shortlist" feedback.
- **Owner:** Product + frontend + backend.

### F-12 — No share capability
- **Severity/Frequency/Confidence:** S2 / F4 / C4
- **Observed:** No share UI; `/share/abc123` → 404. Stated workflow "share with friends" unachievable; only file exports exist.
- **Remediation:** Read-only share links with short-lived tokens; or export-to-My Maps deep link guidance.
- **Owner:** Product + backend.

### F-13 — Map basemap fails with "API KEY REQUIRED" watermark
- **Severity/Frequency/Confidence:** S2 / F4 / C3 (reproduced across reloads; note: could be environment-specific referer/key enforcement)
- **Observed:** All `cartocdn` tile requests return `status 0` (blocked); huge diagonal watermark over map; markers still render. Screenshot captured mid-session.
- **Remediation:** Register app domain with CARTO / use entitlement-compliant tiles or alternate provider; add tile-error fallback UI.
- **Owner:** Infrastructure + frontend.

### F-15 — Multi-city shortlist produces meaningless map & directions
- **Severity/Frequency/Confidence:** S2 / F2–F3 / C3
- **Observed:** After searches in Catania, Berlin, Paris, Rome: map zoom 4 covering a continent; "Open in Google Maps" builds a 10-stop directions URL mixing 4 cities (KML "full set" mixes all).
- **Remediation:** Segment shortlist by destination; show per-city tabs; warn before mixed-city export.
- **Owner:** Product + frontend.

### F-16 — Accessibility issues (observed subset)
- **Keyboard/focus:** tab order logical; but focus styles exist only for chat input border (no visible outline on most buttons); after switching tabs focus stays on stale element; modal doesn't trap or restore focus; Escape doesn't close modal (verified).
- **Semantics:** chat log has no `role="log"`/`aria-live` (new agent messages are never announced); clarifying questions are click-only divs (not focusable, no button role); emoji-only buttons (11 of 13 have no accessible name beyond emoji); both form inputs lack `<label>` (placeholder-only); drop-zone div has no role/tabindex — keyboard users can't trigger the file dialog.
- **Contrast:** `.empty-hint` ≈ 3.04:1 on its background (below AA 4.5:1 for normal text).
- **Touch:** chips ~26px height; tab buttons 64–86px tall but narrow; export buttons 0×0 px on mobile (hidden overflow).
- **Motion/timing:** loading spinner is aria-invisible; 31s waits unannounced.
- **No formal compliance claim** — heuristic + automated spot checks only (no screen reader, no full WCAG 2.1 audit).

---

## 5. Journey-by-journey results

| # | Journey | Persona | Result | Key observations | Time/latency | Friction | Recovery | Confidence |
|---|---|---|---|---|---|---|---|---|
| J1 | First-run orientation | New user | ✅ Completed | Clear welcome, 3 quick prompts, honest dual-score explainer on cards; no help/docs link anywhere | Page load <1s desktop | No "what is this/privacy" info; no favicon | n/a | C4 |
| J2 | Search & recommendations | Returning | ✅ Completed | Places rich (rating, reviews, address, reason, scores); heuristic labeling honest | **31.2s first**; 8–15s after | F-04, F-10, F-01(XSS), F-20 | Retry manual | C4 |
| J3 | Clarifying questions | Returning | ✅ Completed | Questions clickable → prefill; notebook prefs update | ~9s | F-14 prefill-overwrite; questions disappear after send | Partial | C4 |
| J4 | Feedback loop | Returning | ❌ **Failed** | Click does nothing; JS syntax error; no API call; no learned chips ever | n/a | F-02 blocking | None | C4 |
| J5 | Map view | Returning | ⚠️ Degraded | 3→12 markers render, popups, stop cards sync | <1s | F-13 watermark; F-15 multi-city zoom-4 | n/a | C4 |
| J6 | Exports | Returning | ✅ Completed | CSV/KML well-formed, dual scores; Maps URL capped at 10 with toast; KML skips no-coords with toast | <0.5s client-side | F-09 raw enum; F-19 sort mismatch | n/a | C4 |
| J7 | Refresh resume | Returning | ❌ Partial failure | Chat wiped; notebook persists; no user explanation | — | F-03; also multi-tab shares session silently | Manual re-ask | C4 |
| J8 | Takeout import | Returning | ✅ Completed (JSON, ZIP, CSV, invalid) | Spinner ok; success via blocking alert; errors via blocking alert with raw error text; CSV path for "Want to go" accepted | ~25s for 4 places (Gemini) | F-06; F-18 no how-to; invalid-file error is developer-speak | Poor (alert only) | C4 |
| J9 | Profile comprehension | New user | ⚠️ Misleading | Defaults look learned (F-07); after import, real profile replaces it; weight changes after feedback untestable (J4 broken) | — | F-07 | n/a | C4 |
| J10 | Share with friends | Returning | ❌ Not possible | No UI, no routes | — | F-12 | n/a | C4 |

---

## 6. Accessibility findings (heuristic, partial)

- **Keyboard:** Tab order logical (upload→reset→chips→input→send→tabs); **but** modal not focus-trapped, Escape ignored, drop-zone unreachable by keyboard, clarifying questions not focusable (div onclick).
- **Focus visibility:** Only `:focus` rule is a border-color change on chat input; buttons rely on UA default outline (weak on dark theme).
- **Semantics:** `aria-label`/`aria-live`/`role` count = **0** across the app; chat stream not announced; both inputs unlabeled; heading structure otherwise sane (single h1).
- **Contrast:** empty-hint 3.04:1 (fail); status pill 6.99:1 (pass); sender name 5.78:1 (pass).
- **Touch:** chips 26px, export buttons 0×0 on mobile — fails 44px guidance.
- **Zoom:** 200% page scale OK (no clipping) ✅.
- **Motion:** spinner has no `prefers-reduced-motion` handling (minor; single animation).
- **Not tested (limitations):** screen readers (NVDA/VoiceOver), switch access, full WCAG audit, color-blindness simulation, drag-and-drop alternatives via keyboard (upload works via hidden input but discovery is mouse-centric).
- **No compliance claim** is made; this was a heuristic + DOM audit.

## 7. Reliability & performance observations (measured)

| Observation | Measurement | Assessment |
|---|---|---|
| Desktop page load | TTFB 3ms, domInteractive 26ms, load 33ms (warm); ~14KB transfer, 13 resources | Excellent (static assets) |
| First chat response | **30.4s** (`/api/chat` 200) | Poor; cold-start + multi-API pipeline; needs streaming/staging |
| Subsequent responses | 8.4–15s | Poor-to-fair |
| Takeout analysis (4 places) | ~25s, spinner shown | Acceptable with spinner, but blocking alert at end (F-06) |
| Feedback summary API | 189–277ms | Good |
| Map tiles | All `status 0`, 0 bytes — watermark visible | Broken (F-13) |
| Slow-3G emulation | Page loads; app functional; Leaflet OK | OK |
| Offline chat | Clear error card; message lost from input; no retry | F-10 |
| Console errors (normal flows) | None besides the feedback onclick SyntaxError | — |
| Duplicate submission | Double chip-click sends message twice → two LLM calls (observed "Excellent choice! Berlin…" once after both; input cleared synchronously prevents mouse double-click but not programmatic/Enter racing) | Minor cost risk |
| Session handling | Random ids in localStorage; shared across tabs (same profile, no cross-tab sync of chat); Reset regenerates session id only | F-03/F-11 context |

## 8. Analytics and support evidence

**Unavailable.** No analytics, telemetry, error tracking, or support data were provided or publicly accessible. All findings are from direct observation and code inspection; no drop-off/rage-click inferences are made. (Recommendation: add privacy-respecting product analytics + Sentry-class error tracking before broader exposure.)

## 9. Quick wins (low risk, high value)

1. **Fix feedback onclick** (F-02) — event delegation; ~30 lines; unblocks the headline feature. *Validate: click-through + `/api/feedback` 200.* Risk: low.
2. **Escape agent markdown before render + DOMPurify** (F-01) — closes XSS. *Validate: probe string inert.* Risk: low.
3. **Replace alert/confirm with existing toast/modal infra** (F-06). Risk: low.
4. **Persist chat messages per session & replay on load** (F-03). Risk: medium-low.
5. **Default-profile empty state** (F-07) + **friendly enum mapping** (F-09). Risk: low.
6. **Add Takeout how-to link + 2-step instructions in modal** (F-18). Risk: none.
7. **Retry button + input restoration on chat failure** (F-10). Risk: low.

## 10. Strategic improvements

1. **Responsive redesign** (F-05) — mobile-first layout pass, bottom nav tabs, touch target audit. Depends on: design capacity.
2. **Streaming agent responses + staged status** (F-04) — SSE/WebSocket; prewarm Cloud Run min-instances=1 to kill cold starts; requires backend rework of `collaborate()`.
3. **Itinerary as first-class object** (F-11, F-12, F-15) — explicit save/remove/reorder, per-destination itineraries, shareable read-only links (Firestore-backed), My Maps deep-link guidance. Sequencing: data model → UI → share.
4. **Accessibility program** (F-16) — semantics, labels, focus management, contrast tokens; sequence after responsive work (same surfaces).
5. **Observability** — structured logging, request IDs surfaced in UI errors, Sentry, privacy-friendly analytics; informs F-04/F-10 diagnosis with real data.
6. **Honest-status layer** (F-08) — health-driven indicator, capability messaging ("demo data mode" when Places key absent), model-name decoupled copy.

## 11. Recommended remediation roadmap

### Immediate (this week)
- F-01 XSS fix + CSP (security).
- F-02 feedback buttons (core journey broken).
- F-13 map basemap entitlement (core surface broken).
- F-06 blocking dialogs (trust/automation/mobile blockers).
- F-03 chat persistence (data-loss perception).

### Near-term (2–6 weeks)
- F-04 streaming + cold-start mitigation.
- F-05 responsive layout.
- F-07/F-08 honest states and copy.
- F-09/F-10/F-18/F-19 quick UX fixes.
- F-11 explicit shortlist curation UI.

### Medium-term (1–3 months)
- F-12 sharing & itinerary objects; F-15 per-destination segmentation.
- F-16 full accessibility program.
- Analytics/observability foundation.

### Research required
- Real-user latency tolerance and mobile usage share (needs analytics).
- Whether users understand dual scores (needs interviews).
- Takeout drop-off funnel (needs telemetry).
- Optimal feedback model (needs A/B + interviews, after F-02 fix makes feedback possible at all).

## 12. Testing limitations

- **Not tested:** real mobile devices (emulation only), Safari/Firefox, screen readers, load/DoS (prohibited), authenticated flows (none exist), quota-exhaustion paths, very large Takeout files (>150 places truncated by design — inferred from code, not exercised end-to-end), Firestore outage behavior, Vertex quota errors.
- **Prohibited:** security exploitation beyond the single non-destructive XSS probe (self-contained flag, no exfiltration); no fuzzing; no third-party domain testing (google.com/maps links constructed but not opened beyond verifying URL shape).
- **Hypotheses (need engineering confirmation):** cold-start contribution to 31s; CARTO watermark cause (referer/key registration); rate-limit behavior.
- **Requires real humans:** value-proposition clarity, trust in AI scores, comprehensibility of "heuristic shortlist" label.
- **Requires staging:** destructive edge cases, quota tests, Firestore failure injection.

## 13. Final assessment

- **Three most urgent fixes:** F-01 (XSS), F-02 (feedback buttons), F-03 (persistence) — in that order; F-13 immediately after.
- **Three highest-leverage improvements:** streaming/status transparency; responsive mobile layout; itinerary curation + sharing.
- **Most important unknown:** actual user-side latency tolerance and mobile share of usage (no analytics).
- **Ready for broader exposure?** **No.** The XSS must be fixed first (public, unauthenticated, script execution), then the broken feedback loop, before inviting real traffic.
- **Next five tests:** (1) real-device mobile pass, (2) screen-reader pass on chat + upload, (3) 150+ place Takeout file end-to-end, (4) staged error-injection in staging (Vertex quota, Firestore down), (5) cross-browser Safari/Firefox smoke.

---

*Evidence retained in `evidence/` (screenshots). Session IDs/user IDs referenced in raw notes were synthetic and have been redacted from this report. No production data was altered; no messages outside the app under test were sent.*
