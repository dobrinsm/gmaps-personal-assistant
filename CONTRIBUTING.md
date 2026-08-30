# Contributing to GMaps Personal Assistant

## Ground rules
1. **No secrets in git, ever.** No `.env`, key files, tokens. The Dockerfile strips `backend/.env`; keep it that way. Use `.env.example` for new variables (placeholders only).
2. **Additive schemas only.** Never remove/rename API fields or Firestore keys — `taste_match_score` back-compat is a contract. Old documents must keep rendering.
3. **Honest scores rule.** Never fabricate a score on failure. Unscored → deterministic heuristic, labeled `scored_by="heuristic"`. There is a regression test — keep it passing.
4. **Weights are code-mutated.** The LLM may narrate learned preferences but never writes them.
5. **Contract tests first.** Ranking, feedback math, and export shapes are pinned by `tests/`. Change behavior → change the test in the same commit, and explain why.
6. **Google-stack identity.** Gemini/Vertex + Cloud Run + Firestore + Places API (New). No new GCP services without an ADR.

## Workflow
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt pytest httpx ruff

# before committing
python -m pytest tests/ -q
node tests/test_frontend_exports.js
ruff check backend/ tests/
node --check frontend/app.js
```

## Commit style
Small, incremental, imperative subject lines with the feature tag, e.g. `feat(ranking): ...`, `fix(map): ...`, `test(memory): ...`.

## Security reviews
Any change touching `user_id` scoping, prompt construction, CORS, or export generation should state in the PR description: what data reaches the model, what reaches other users (answer: none), and what is escaped in the browser.
