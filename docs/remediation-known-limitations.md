# Remediation Known Limitations

**Batch 1 (2026-08-30) — what this remediation does NOT cover and why.**

## Deferred by design (tracked, not forgotten)
| Finding | Why deferred | Dependency | Suggested next step |
|---|---|---|---|
| F-04 full fix (streaming, cold start) | Requires reworking the synchronous `collaborate()` pipeline to SSE; too risky for a single session. Interim: staged wait copy + expectation text. | Backend rework + Cloud Run `min-instances` | Implement SSE streaming of agent stages; set min-instances=1 |
| F-11 auto-shortlist / no curation | Product decision needed (explicit save vs. auto+remove). We chose not to redesign the shortlist data model in a bugfix batch. | Data-model change | Add "save/remove" actions on place cards + shortlist; keep auto-add behind a flag |
| F-12 share with friends | New feature (auth-less read-only tokens) — needs its own security review before existing on an unauthenticated app | F-01 fix (landed) + token design | Spec read-only share tokens |
| F-15 per-destination itineraries | Depends on F-11's data model | Same as F-11 | Segment shortlist by destination in the notebook |
| F-13 map basemap watermark | **Not a code defect** — CARTO tile entitlement/referer is deployment configuration | Cloud Run domain registration on CARTO / alternate provider | Register the production URL or switch provider; add tile-error fallback UI at that time |

## Partially fixed
- **F-04**: only the perception layer (staged wait text, expected duration, send-lock). Actual latency (8–30s) is unchanged — needs streaming and/or prewarming.
- **F-16 accessibility** — targeted subset only (labels, dialog semantics, Escape, focus visibility, contrast of empty-state text, reduced motion). **Not done:** full screen-reader pass, focus trap inside the modal, live region for the whole chat stream, drop-zone keyboard alternative beyond the hidden input label, full WCAG audit. No compliance claim is made.

## Test-environment caveats
- Browser E2E ran against a **mock backend** (real Gemini/Places/Firestore are external); place cards, feedback POST, exports, and replay paths were exercised for real, but model-generated content shape may vary — the escaping fixes are asserted at the unit level for arbitrary payloads.
- The XSS probe suite covers `<img>/<svg>/<script>/<iframe>` payloads and the audit's original probe; it does not replace a dedicated security review, and a strict `Content-Security-Policy` header is still **recommended** (needs Cloud Run response-header config, not frontend code — cannot be done in-repo).
- `is_default` flag: pre-existing production user documents lack the flag; they are treated as real profiles (correct), but the flag only appears for users created **after** this deploy.
- The localhost→`127.0.0.1:8000` API_BASE dev redirect was kept as-is (backward-compatible with local dev); it is irrelevant in production (non-localhost origins use same-origin).

## Not done on purpose
- No production deployment, merge, or env changes from this task.
- No destructive testing against production; the XSS probe was validated locally against the fixed build only.
- F-11/F-12/F-15 feature work was deliberately not "smuggled in" as fixes.
