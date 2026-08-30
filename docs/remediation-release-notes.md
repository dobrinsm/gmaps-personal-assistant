# Remediation Release Notes — production-audit batch 1

**Branch:** `remediation/production-audit-2026-08-30` · **Date:** 2026-08-30
**Based on:** production user-testing audit (docs/user-testing-report.md, 2026-08-30)

## Fixed in this batch (user-visible)

### Security
- **XSS in chat/agent output (F-01, S4).** Model output and external place data are now HTML-escaped before rendering. Probe strings that executed script in the audited production build now render as inert text.
- **Feedback buttons dead (F-02, S4).** 👍 / 🚩 / 🎭 now actually record feedback (previously every click threw a JavaScript error and nothing was saved). The "Learned from your feedback" chips now populate after use.

### Reliability & data safety
- **Conversation is restored after refresh (F-03).** The backend always persisted turns; the UI now replays them with a "Restored conversation from your last visit" divider.
- **No more lost messages on errors (F-10).** If a chat turn fails, the typed message is returned to the input box with a clear explanation; double-submits during a pending turn are blocked (input/send disabled).
- **Honest wait feedback (F-04 interim).** The wait card states 10–30s expectations and rotates staged status text.

### UX
- Upload flow: non-blocking success toast + auto-open of the Profile tab; friendly, actionable error copy (not-takeout / no-places / too-large / network) instead of raw JSON errors; Google Takeout how-to link + 3 steps in the modal (F-06, F-18).
- Reset is a two-click confirm with visible armed state (F-06).
- Mobile layout: panes stack below 900px, sticky chat input, 44px touch targets (F-05).
- Price levels humanized in place cards and exports (`Moderate ($$)` instead of `PRICE_LEVEL_MODERATE`) (F-09).
- Notebook preference chips show human labels (F-17); clarification clicks append instead of overwriting typed text (F-14); map-tab hint matches export ordering (F-19); 5000-char input soft cap with notice (F-20); empty "learned" section hidden (F-21); favicon added (F-22).

### Accessibility (targeted)
- Upload modal: dialog semantics, Escape-to-close, focus moved in/out.
- Clarifying questions keyboard-operable; visible focus outlines app-wide; labeled inputs; empty-state contrast ≥ 4.5:1; `prefers-reduced-motion` respected (F-16).

### Honesty & trust
- New users see "No taste profile yet…" instead of fabricated defaults; the header pill no longer claims a specific model is "Active"; the upload spinner no longer names a model (F-07/F-08).

## Migration / config
- **No database migrations.** `is_default` is written only for newly created (default) profiles; existing documents are untouched and keep working (absence of the flag = real profile).
- No new environment variables, dependencies, or endpoints.
- **Deploy-time action required (not code):** register the Cloud Run service URL with the CARTO basemap (or switch tile provider) to fix the "API KEY REQUIRED" map watermark — audit finding F-13. This is configuration on the tile-provider side and cannot be fixed in-repo.

## Known limitations (details in remediation-known-limitations.md)
- First-response latency unchanged (~8–30s); streaming deferred.
- Shortlist auto-population (no manual remove/save) unchanged.
- Sharing/per-destination itineraries not started.

## Recommended rollout
1. Deploy to staging, run the audit journey scripts (chat → feedback → refresh → export).
2. Verify in staging that `is_default` appears only for brand-new user ids and that existing users' Profile tab is unchanged.
3. Ship behind normal Cloud Roll revision traffic; keep previous revision for instant rollback.
4. Watch: console error rate (should drop to ~0 for the feedback SyntaxError), `/api/feedback` request rate (new traffic from working buttons), 4xx/5xx on `/api/chat`.
