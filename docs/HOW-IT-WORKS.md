# How Summit 2.0 Actually Works

This is the operational doc — how to run it, how a request flows end to end,
and where every moving part lives. `STORY.md` is the talk script.
`DEMO-DETAIL.md` is the deep technical/anecdotal dive per attack. This is
the "I need to set it up, extend it, or debug it" doc.

---

## 1. Run it

Same container as the original DEFCON demo — Summit 2.0 is an additive
router bolted onto it, not a separate service.

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Required for the base demo (Acts 1–3)
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0
LLM_PROVIDER=bedrock

# Required only for Act 4 (Trend AI Guard) — omit and Act 4 fails closed
V1_API_KEY=<Trend Vision One API key, a JWT>
V1_REGION=sg
V1_APP_NAME=pretty-please
```

```bash
docker compose up
open http://localhost:9000/summit2/
```

No AWS profile — Bedrock auth is via EC2 instance role / IMDS, same as the
base demo. No `V1_API_KEY`? Act 4 still loads; every AI Guard call returns
`{"action": "Block", "reasons": ["V1_API_KEY not set — AI Guard disabled"]}`
(fail-closed, not a crash — see `middleware/aiguard.py:50,56,76`).

Nav: `index.html`'s existing `🧱 Summit Demo` link now points at `/summit2`
(label `🧱 Summit 2.0`) — the only line touched in a DEFCON-protected file.
The original `/summit` demo is untouched and still reachable directly.

---

## 2. The file map

Everything Summit 2.0 owns is new and additive. Nothing DEFCON owns was
rewritten — only imported.

```
app/
├── routes_summit2.py          ← the router: every /summit2/* endpoint
├── static/
│   ├── summit2.html           ← the 4-act UI (Alpine.js, no build step)
│   └── summit2.js             ← Alpine component: state, badges, thinking anim
├── middleware/
│   ├── layered_engine.py      ← L1–L9 à la carte guardrail composition
│   ├── call_classifier.py     ← Act 3: async write-ahead-log + poll classifier
│   ├── aiguard.py             ← Act 4: Trend Vision One AI Guard client
│   └── extra_seed_data.py     ← 2 extra patients (contrast pair, additive rows)
├── db.py                      ← +2 tables (ai_calls_log, ai_calls_classified), +seed fn
├── main.py                    ← +router include, +startup hooks (additive only)
└── agents/plain.py            ← +optional model_id override param (additive only)
```

Everything Summit 2.0 **imports but never edits**: `guardrails.py`,
`tools_vibe.py`, `tools_fortress.py`, `memory.py`, `prompts.py`, `auth_sig.py`,
`db.conn`. That's deliberate — the fixes it demonstrates are DEFCON's real
fixes, reused, not reimplemented for effect.

---

## 3. Request flow — a chat message, end to end

```
Browser (summit2.html/js)
   │  POST /summit2/api/chat  { message, caller_id, act, fix_bundle, ai_guard }
   ▼
routes_summit2.py : api_chat()
   │
   ├─ 1. layers = cumulative layer set for the selected act/fix_bundle
   │      (Act 1 → [], Act 2 → union of fix bundles up to selected,
   │       Act 3 → ["L7"] always)
   │
   ├─ 2. if ai_guard: aiguard.check_prompt(message)
   │      → real call to Trend V1 /applyGuardrails, fail-closed on error/timeout
   │      → Block ⇒ short-circuit, return synthetic "blocked" trace entry
   │
   ├─ 3. history_key = (session_id, caller_id) if "L7" in layers else session_id
   │      → look up / append to the in-memory conversation history dict
   │      → THIS line (routes_summit2.py:311) is the real fix for Attack 5.
   │         memory.py's fortress_get/append exist and are correct, but
   │         are a decorative side panel only — never on this path.
   │
   ├─ 4. get_schemas(caller_role, layers) → the tool list the model sees
   │      → L2 active: role-scoped list, no admin tools for a patient caller
   │      → L3 active: query_database removed from the list entirely
   │
   ├─ 5. plain_run(history, schemas, model_id=...) → Bedrock Converse call
   │      → model picks 0+ tool calls
   │
   ├─ 6. for each tool call → layered_engine.dispatch(tool_name, args, caller,
   │        session_id, layers)
   │        a. ToolBudget.charge_call() / LoopDetector.check() — L8, if active
   │        b. authz_own_or_caregiver() — L4, if active
   │        c. tool-specific admin-role check — L2 dispatch-side backstop
   │        d. actual tool fn call (vibe_call / fortress equivalents)
   │        e. wrap_untrusted() on note content — L5, if active
   │        f. redact_pii() before logging — L9, if active (never on live result)
   │        → returns (result, trace) — trace is the literal step list the
   │          "Layer Pipeline" sidebar panel renders
   │
   ├─ 7. call_classifier.log_call(...) — fire-and-forget INSERT into
   │      ai_calls_log, classified=0. Zero added latency; a background
   │      asyncio task (started in main.py's startup()) polls every 5s,
   │      batches unclassified rows, classifies via Nova Micro, writes
   │      ai_calls_classified. This is what feeds the Act 3 classifier meter.
   │
   ├─ 8. if ai_guard: aiguard.check_response(final_text, model_id)
   │      → same fail-closed contract as step 2, applied to the model's
   │        own output before it reaches the browser
   │
   └─ 9. return { text, tool_calls: [...], trace, subject, aiguard: {...} }
   ▼
Browser: summit2.js renders each tool_calls[] entry as an expandable
Agent Activity card (Decision/Arguments/Result/Reasoning/Layer pipeline),
badgeFor(tc) colors it ALLOWED/LEAKED/BLOCKED/UNGUARDED based on
tc.subject.is_caller + trace pass/fail — NOT on whether the call merely
succeeded, which is the whole point (a successful call can still be a leak).
```

---

## 4. The three demo dimensions, and how they combine

Summit 2.0 has three independent axes a request can vary along — this is
why "4 acts" isn't really 4 separate code paths, it's 3 knobs:

| Axis | Values | Where it's read |
|---|---|---|
| **Act** | 1 (vibe) / 2 (fix bundles) / 3 (traced) / 4 (content guard) | picks which UI panel renders + which layer set / ai_guard default applies |
| **Layers** (`L1`–`L9`) | cumulative union up to selected fix bundle | `layered_engine.dispatch()` / `get_schemas()` |
| **AI Guard** (`ai_guard: bool`) | on/off, independent of layers | wraps `api_chat()`'s input/output, orthogonal to L1–L9 |

Act 4 defaults `ai_guard=true` but a request in *any* act can carry it —
Act 2's fix bundles and Act 4's content guard are deliberately composable,
not mutually exclusive, because access control and content moderation are
answering different questions (see `DEMO-DETAIL.md` Part 4 for why that
distinction matters).

---

## 5. Data model

Shared SQLite tables with DEFCON (`patients`, `labs`, `notes`,
`appointments`, `caregivers`) — Summit 2.0 adds **rows**, not new tables,
via `extra_seed_data.py`'s `seed_summit2_extras()` (2 extra patients: Tomas
Rieger #104 + caregiver Grace Okonjo #105, a second legit-caregiver
contrast pair alongside the existing Alex Chen #7 / Mei Chen #18 pair).
Called from `main.py`'s `startup()` and the existing 5-minute `_reset_loop()`
— reseeded every reset, same lifecycle as DEFCON's own data.

Two genuinely new tables, `db.py`'s `SUMMIT2_SCHEMA`:

- **`ai_calls_log`** — every tool/model call, write-ahead, `classified=0`
- **`ai_calls_classified`** — poll-loop output: category + `classifier_cost_usd`

---

## 6. Extending this

- **New attack demo:** add to `ATTACK_BUNDLES` in `routes_summit2.py` — no
  new endpoint needed, `/api/chat` already handles arbitrary prompts per
  caller/act.
- **New fix layer:** add to `LAYERS` in `layered_engine.py`, wire the check
  into `dispatch()`, add to a `FIX_BUNDLES` entry. Keep the cumulative-union
  logic in `summit2.js`'s `cumulativeLayers()` in mind — a new layer only
  shows up in later bundles if you add it to the union, not just the one
  bundle you meant it for.
- **New AI Guard prompt:** add to `AIGUARD_CATALOGUE` — but verify it
  against the real Trend endpoint before shipping (see `DEMO-DETAIL.md`
  Part 5.1 for why a simplified test doesn't predict real behavior).

---

## 7. What NOT to touch

DEFCON protection list — same as always, additive-only or fully forbidden:
`app/main.py` (additive only), `app/static/index.html` (the one nav-link
line, already spent), `app/static/app.js`, `app/attacks/**`, `app/db.py`
(additive only), `app/matrix_test.py`, `app/verification/**`,
`app/tools_fortress.py`, `app/tools_vibe.py`, `app/prompts.py`,
`app/seed_data.py`, `app/guardrails.py`, `app/memory.py`, `app/audit.py`,
`app/auth_sig.py`, `app/log_store.py`.
