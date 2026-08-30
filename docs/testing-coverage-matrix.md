# Testing Coverage Matrix — GMaps Personal Assistant

**Date:** 2026-08-30 · **Environment:** Headless Chromium 151 (CDP) · Viewports: 1440×900, 768×1024, 375×667, 200% zoom · Network profiles: default, Slow-3G, offline
**Legend:** ✅ tested & passed · ⚠️ tested with issues · ❌ failed / broken · ⬜ not tested (reason) · 🔌 tested indirectly (code/DOM inspection only)

## Journeys × Environment

| Journey | Desktop 1440 | Tablet 768 | Mobile 375 | Slow-3G | Offline | Fresh profile | Returning profile |
|---|---|---|---|---|---|---|---|
| J1 First-run orientation | ✅ | ✅ (layout only) | ⚠️ F-05 | ⚠️ loads ok | ⬜ | ✅ | ✅ |
| J2 Chat recommendations | ⚠️ (31s, XSS) | ⬜ | ⚠️ (layout) | ⬜ | ⚠️ error path | ✅ | ✅ |
| J3 Clarifying questions | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ✅ |
| J4 Feedback (👍/🚩/🎭) | ❌ broken | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ❌ |
| J5 Map view | ⚠️ (tiles fail) | ⬜ | ⬜ (0×0 buttons observed) | ⬜ | ⬜ | ✅ (empty state) | ⚠️ |
| J6 Exports (Maps/KML/CSV) | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ✅ |
| J7 Refresh resume | ❌ (chat lost) | ⬜ | ⬜ | ⬜ | ⬜ | n/a | ⚠️ |
| J8 Takeout import | ✅ (json/zip/csv/invalid) | ⬜ | ⬜ | ⬜ | ⬜ | ✅ | ✅ |
| J9 Profile comprehension | ⚠️ (fake defaults) | ⬜ | ⬜ | ⬜ | ⬜ | ⚠️ | ✅ |
| J10 Share | ❌ absent | ❌ | ❌ | ⬜ | ⬜ | ⬜ | ❌ |

## Feature-level checks

| Feature/Behavior | Result | Evidence type |
|---|---|---|
| Health endpoint `/api/health` | ✅ 200, correct payload | HTTP probe |
| Unknown routes (`/notebook`,`/itinerary`,`/share/*`) | ⚠️ raw JSON 404, no SPA fallback/no custom page | HTTP probe |
| `/docs` + `/openapi.json` exposure | ⚠️ public (info disclosure, low risk; note only) | HTTP probe |
| Quick-prompt chips | ⚠️ double-click → duplicate API calls | Interaction |
| Clarifying-question dock | ⚠️ prefill overwrite; disappears post-send | Interaction |
| Toast system (feedback/export notices) | ✅ renders (but feedback never triggers it — F-02) | DOM |
| CSV export structure | ✅ RFC-style quoting, dual scores, ids | Content inspection |
| KML export | ✅ valid XML, CDATA, skips no-coords + toast | Content inspection |
| Google Maps directions URL builder | ✅ caps 10 stops + overflow toast | JS inspection |
| Places w/o coordinates | ✅ kept in notebook, excluded from map/KML, labeled "no coords" | DOM + JS |
| Empty shortlist map state | ✅ correct empty state | DOM |
| Reset session (confirm) | ⚠️ works, but native confirm + full reload | Interaction |
| localStorage identity | ⚠️ random ids; shared across tabs; no cross-tab sync | DOM/localStorage |
| Multi-destination session | ⚠️ single mixed shortlist (F-11/F-15) | DOM + map zoom |
| gibberish input handling | ✅ graceful clarification | Chat |
| 5k-char input | ⚠️ accepted, no limit (F-20) | Boundary |
| XSS probe (agent echo) | ❌ executed (F-01) | DOM + flag |
| XSS probe (user message render) | ✅ escaped correctly (escapeHtml on user path) | DOM |
| Rapid repeated clicks (chip) | ⚠️ duplicate sends | Interaction |
| Refresh during loading | ⬜ not explicitly tested (refresh between turns only) — noted gap | — |
| Modal a11y (Esc/focus trap) | ❌ Escape ignored, no trap (F-16) | Keyboard/CDP |
| Tab focus order | ✅ logical | CDP key events |
| 200% zoom | ✅ no clipping | Emulation |
| Takeout invalid file | ⚠️ 400 + raw error in alert (F-06) | Alert capture |
| Takeout empty features | ✅ correct error copy ("No saved places found…") | Alert capture |
| Takeout ZIP (nested path) | ✅ parsed, profile built | Profile change |
| Heuristic shortlist labeling | ✅ label rendered when `scored_by=heuristic` (from code path; none observed live — all LLM-scored) | Code + DOM |
| Feedback-summary API | ✅ 200 fast (UI chips never populated — upstream F-02) | Network |

## Not covered (and why)

| Area | Reason |
|---|---|
| Load/stress, rate limits | Prohibited by test policy |
| Destructive/fuzz security testing | Prohibited |
| Real mobile devices, Safari/Firefox | Not available in environment |
| Screen readers (NVDA/VoiceOver/JAWS) | Not available; heuristic AX audit only |
| Very large Takeout (>150 places) | Code truncates at 150 (inferred); not exercised end-to-end to avoid heavy prod processing |
| Vertex/Firestore failure injection | Requires staging; not attempted on prod |
| Quota exhaustion / rate-limit UX | Not triggered (risk of real quota impact) |
| Payment/emails/etc. | N/A — no such features exist |
| Longitudinal memory/weight adaptation over days | Out of session scope; J4 broken anyway |
