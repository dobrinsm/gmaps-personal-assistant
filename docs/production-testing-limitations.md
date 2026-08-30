# Production Testing Limitations — GMaps Personal Assistant

**Audit date:** 2026-08-30 · **Auditor:** Automated agent (synthetic browser-based testing) · **Policy:** Read-only production testing

## 1. Environment and tooling constraints
- Testing used **headless Chromium 151** (CDP automation) only. Safari, Firefox, Edge, and real mobile devices were unavailable. Mobile findings are from **emulated** viewports (375×667, 768×1024) with touch emulation — real touch ergonomics, OS-level zoom, and mobile keyboards were not exercised.
- The session ran from a single geographic location (single egress region). **Cloud Run cold-start behavior may differ** for other regions; the 31s first response includes a cold-start component that is hypothesized, not isolated.
- Map-tile failure (F-13, "API KEY REQUIRED" watermark) was reproduced across reloads in this environment, but the root cause (CARTO key/referer registration) is inferred. A registered production referer could behave differently for other visitors — engineering must confirm.

## 2. Prohibited and therefore untested
- Load, stress, DoS, or rate-limit testing — prohibited. Concurrency behavior (e.g., many simultaneous `/api/chat` calls, Firestore contention) is **unknown**.
- Fuzzing, brute force, destructive security testing — prohibited. The single XSS probe was non-destructive and self-contained (a flag set in page JS; no data left the page).
- Any third-party domain testing (including opening constructed Google Maps URLs in a live browser session beyond verifying URL structure).
- Quota-exhaustion scenarios (Vertex AI / Places API) — could have consumed real quota or degraded the service.

## 3. Accounts and data
- The app has **no authentication**; identities are random localStorage ids. Only synthetic identities were created (`user_*`, `sess_*`), plus four tiny synthetic Takeout fixtures (4 places each). No real customer data was used; nothing was deleted or overwritten beyond the auditor's own synthetic session documents.
- Feedback writes were **untestable via UI** (F-02 breaks the request entirely), so the downstream memory/weight-adaptation loop (README's core claim) could not be validated end-to-end. Feedback behavior is inferred from code (`db.py`, `agent.py`) and marked as such.
- Very large Takeout archives (>150 places) were not uploaded: the backend truncates to 150 samples by design (`agent.py build_taste_profile_from_places`), so an end-to-end test would mostly exercise the truncation path; flagged for staging verification instead.

## 4. Analytical limitations
- **No analytics, telemetry, logs, or support data were available.** All frequency ratings (F1–F4) are based on how many *tested paths* reproduced each issue, not on real-user prevalence. They should be re-based on real telemetry when available.
- No real human users were observed, recruited, or surveyed. **Nothing in this report should be read as user research.** Comprehension, trust, and satisfaction claims require moderated testing.
- Latency figures are single-run samples from one client location (not a distribution): 30.4s / 8.4s / ~9s / 12s+ across a handful of calls. p50/p95 require proper measurement.
- Accessibility review was heuristic + DOM/AX-structure based with keyboard/CDP input simulation. **No screen reader, switch access, or full WCAG 2.1 audit was performed. No compliance claim is made.**
- Severity/priority scoring reflects user-impact reasoning from observation; business-importance weighting (real usage share by device, retention impact) is unverified.

## 5. Conclusions that remain hypotheses (require validation)
| Hypothesis | Required validation |
|---|---|
| 31s first response is dominated by cold start + sequential Places→LLM pipeline | Cloud Run logs, min-instances test, tracing |
| CARTO watermark = unregistered referer/key for the Cloud Run URL | Tile provider console / referer test from allowed domain |
| Duplicate chip-click sends double-bill LLM/Places quota | Backend logs (2 requests observed client-side; server dedupe unknown) |
| Large Takeout files time out on Cloud Run (body-size / CPU limits) | Staging replay with 5–50MB archives |
| Refresh during an in-flight `/api/chat` loses the turn server-side | Instrumented staging test |
| `/docs` exposure is intentional demo behavior | Owner confirmation; consider disabling in prod |

## 6. What real-human testing must cover next
1. Moderated first-run: "what does this app do / what would you type first?"
2. Comprehension of dual scores ("I 9 · T 9 → 9") and the "heuristic shortlist" label.
3. Mobile task completion (import Takeout on a phone is likely a hard stop today).
4. Trust reactions to AI-generated scores and to the auto-populated shortlist.
5. Latency tolerance (31s) — abandon thresholds before and after streaming fix.

## 7. Preconditions for the next test cycle
- A **staging environment** with quota ceilings, fake keys, and failure injection (Firestore outage, Vertex 429) — several backend failure paths were untestable on prod by policy.
- Privacy-respecting analytics (funnel: land → first chat → response → shortlist → export) and error tracking (console + backend 5xx), to replace heuristic frequency ratings with real drop-off data.
- Real-device lab (iOS Safari + Android Chrome) and one screen-reader pass before accessibility remediation is declared done.
