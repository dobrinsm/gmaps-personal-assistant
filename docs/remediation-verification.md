# Remediation Verification — production-audit batch 1

**Branch:** `remediation/production-audit-2026-08-30`
**Validation date:** 2026-08-30 · **Environment:** local repo + mock backend (no GCP creds required), headless Chromium 151

## Automated checks (all executed on the final HEAD of the branch)

| Check | Command | Result |
|---|---|---|
| Backend unit/contract tests | `.venv/bin/python -m pytest tests/ -q` | **68 passed** (baseline 68 → 68; no tests weakened) |
| Frontend export smoke | `node tests/test_frontend_exports.js` | **27 passed, 0 failed** |
| Frontend security suite (new) | `node tests/test_frontend_security.js` | **24 passed, 0 failed** (includes original audit XSS probe) |
| Lint (Python) | `.venv/bin/ruff check backend/ tests/` | All checks passed |
| Syntax/type sanity | `py_compile` via pytest collection; Pyright LSP diagnostics clean on touched files | OK |
| Browser e2e (fixed frontend + mock API) | see journey re-tests below | all pass |
| Secret scan of diff | `git diff main --name-only` + grep for key/token patterns | clean (see §secret scan) |
| Dependency check | no new dependencies added; `requirements.txt` untouched | n/a |
| Production build | static frontend — no build step exists; `python -c "import backend.main"`-equivalent covered by pytest boot of FastAPI app in `test_api.py` | pass |

Test-file edits:
- `tests/test_frontend_exports.js` — DOM stub extended with `document.addEventListener`/`querySelector` (the F-02 delegated listener needs it). No assertions weakened.
- `tests/test_frontend_security.js` — **new** file, 24 checks.
- `tests/mock_server.py` — **new** fixture server for browser e2e (not used by CI pytest).

## Per-finding verification

| Finding | Original repro | Result after fix | Test type | Status |
|---|---|---|---|---|
| F-01 XSS | Probe `<img src=x onerror=…>` executed via agent reply & place names | `markedParse` escapes before markdown; probe renders as **text** (`&lt;img src=x…`), `window.__xss` never set — verified in live browser with poisoned mock data (screenshot 04/08) + 24 node checks | unit + browser | **Fixed** |
| F-02 feedback buttons | Click → SyntaxError, no API call | Delegated data-attribute handler → POST fires, toast "Feedback recorded: 'like'…", learned chips render — verified in browser (screenshot 05); 30 feedback-button clicks in mock UI produced 1 POST per click | unit + browser | **Fixed** |
| F-03 refresh wipes chat | 5 cards → 1 | After refresh: 4 user + 5 agent cards restored under a "Restored conversation" divider; clarifying dock NOT re-armed; stale questions suppressed | browser | **Fixed** |
| F-04 (interim) | Static "Thinking…" 30s | Wait card rotates 4 honest stages ("Understanding…", "Searching Google Places…", …), states 10–30s expectation; full streaming deferred | browser (throttled) | **Partially fixed (stages shipped; streaming deferred)** |
| F-04a duplicate submits | Double chip-click = 2 LLM calls | Submit is serialized: input+send disabled with "Waiting for the agent…" placeholder; verified lock during a throttled 2.5s turn | browser | **Fixed** |
| F-05 mobile sliver | notebook 28px @375px | Panes stack (375/375), notebook fully visible, tabs sticky, touch targets ≥44px (chips 37px+padding visually 44 incl. hit area via padding) | browser + screenshot 07 | **Fixed** (note below on chips) |
| F-06 blocking dialogs | alert/confirm froze page | Upload success → toast + auto-jump to Profile tab; failures → actionable toasts; Reset → two-click confirm with armed styling + disarm after 6s (verified) | browser | **Fixed** |
| F-07 fake learned profile | fresh user saw fabricated summary/weights as learned | Backend flags `is_default: true`; Profile tab shows "No taste profile yet…" italic empty state (screenshot 06); imports still replace it | unit (API shape) + browser | **Fixed** |
| F-08 overclaiming copy | static "Gemini 3.5 Flash Active" | Neutral "● Agent Ready" pill (id=agentStatusPill) + upload copy without model claims | browser | **Fixed (copy-level)** |
| F-09 raw enums | `PRICE_LEVEL_MODERATE` in exports | CSV/KML show "Moderate ($$)"; cards show "💵 Moderate ($$)" — verified live | unit (export smoke) + browser | **Fixed** |
| F-10 no retry path | offline error, message lost | Error cards name the failure (offline vs server N), input restored (verified: "offline test msg" back in box), retry = re-send | browser | **Fixed** |
| F-14 prefill overwrite | click question destroyed typed text | Prefix now appends after existing text (`"typed text Regarding \"Is this…\""`) — verified | browser | **Fixed** |
| F-16 a11y subset | unlabeled inputs, no Escape, no focus mgmt, 3.0:1 hints, non-focusable questions | Escape closes modal + focus restored; dialog semantics; hidden labels; focus-visible outlines; hint contrast fixed; questions role=button + Enter/Space; reduced-motion | browser + CSS | **Partially fixed** (screen-reader audit still pending — see limitations) |
| F-17 pref keys | `fancy_level: …` shown raw | "Fancy level: nothing fancy" — verified in notebook chips | browser | **Fixed** |
| F-18 no takeout how-to | dead-end modal | Modal links to takeout.google.com + 3-step guide | browser (screenshot 04) | **Fixed** |
| F-19 export-order hint | hint contradicted sort logic | Hint now states exports are score-sorted | copy | **Fixed** |
| F-20 no input cap | 5040 chars accepted silently | >5000 chars trimmed with a toast; verified in code path | code review | **Fixed** |
| F-21 empty learned box | stray empty border | `#nbLearned.empty` hidden until chips exist — verified | browser | **Fixed** |
| F-22 favicon | none | inline SVG data-URI favicon — verified in DOM | DOM | **Fixed** |

**Deferred (not fixed in this batch):** F-04 full streaming, F-11 curation UI, F-12 sharing, F-15 per-destination itineraries, F-13 map-tile entitlement (infra/config, not code — see release notes).

## Regression checks
- Export builders (Maps URL cap, KML CDATA/lng-lat, CSV quoting) — 27/27 unchanged.
- Feedback weight mutation/clamping/user-scoping — 17/17 pytest.
- API contract (chat/health/upload parsing) — 68/68 pytest incl. all pre-existing suites.
- XSS probes inert in both live-DOM and node-level tests; markdown bold/italic/paragraph output unchanged.
- Permissions/data-isolation: feedback-summary user scoping tests still pass; no new endpoints introduced; no auth surface changed.
- No DB schema changes; `is_default` is additive on new/merged profile docs (existing docs unaffected — flag simply absent ⇒ treated as non-default, so real users never see the empty state).

## Validation commands
```
python3 -m pytest tests/ -q                 # 68 passed
node tests/test_frontend_exports.js         # 27 passed
node tests/test_frontend_security.js        # 24 passed  (new)
ruff check backend/ tests/                  # clean
python -m uvicorn tests.mock_server:app ... # browser e2e (this file, above)
```

## Security checks
- Secret scan: no keys/tokens added (grep of full diff for `api_key|AIza|sk-|BEGIN.*PRIVATE|password|token\s*=` → only unrelated code identifiers).
- No credentials committed; mock server binds 127.0.0.1 and ships no secrets.
- XSS regression suite guards the exact production-audit probe.
- No auth/validation logic weakened; rate limiting untouched (none existed); CSP header recommended as follow-up (documented in limitations).

## Rollback
Each finding is an isolated commit on `remediation/production-audit-2026-08-30`; revert commits in reverse order or `git revert a2fc165..HEAD` for the whole batch. No DB migrations, so rollback is a pure image re-deploy.
