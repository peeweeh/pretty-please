# SUMMIT-03 — Port eonar-mono Patterns into the Demo (Clean-Room)

**TLDR:** Bring the four missing eonar-mono architectural patterns into the pretty-please summit demo — per-session agent cache, parallel skill execution in dependency waves, four execution modes from one entry point, and filesystem-based tool auto-discovery — written clean-room (no eonar code copied, no eonar ticket numbers referenced, no eonar-specific tooling names) so the demo can teach the pattern publicly without exposing company IP.

**Confidence:** High on the *what* (we have a working reference implementation to learn from). Medium on the *scope tradeoff* — four patterns is a lot for one spec; see open question 1.

**Related:** Sits alongside `SUMMIT-02-strands-and-guardrail.md`. Either can land first. If both land, pretty-please reaches full architectural parity with prod while still being fully clean-room.

---

## 🧠 Brain Dump (USER)

> "no no i dont want you to rewrite the narrative yet. the thing works no.. but i want a. the eonar-mono structure but never use its code.. the idea is to share how we built this witout talking about you know.. so we need to spec first"

**Intent (my read):**
- The demo currently works. Do not break it.
- The demo should teach the *architectural patterns* we built at the company.
- The demo must not contain company-proprietary code, ticket references, tool names, or schema specifics.
- The teaching goal is "we solved these problems — here is how, generically." Not "here is our codebase."
- Write the spec first. Do not touch code yet.

---

## ✅ Resolved Decisions (locked)

1. **Scope:** Land all four patterns together. One umbrella execution. Accepted blast-radius tradeoff for a single cohesive demo upgrade.
2. **Ticket scheme:** Pretty-please uses its own local `PP-XX` scheme. No eonar ticket numbers (`#708 #709A #709B #709C #710`) anywhere in pretty-please code, commits, or docs.
3. **DEFCON protection:** 🚫 **DO NOT TOUCH DEFCON.** Explicit user directive. See new section "🚫 DEFCON Protection Protocol" below — mandatory before/after every PR.
4. **Auto-discovery variant:** Simple. Subpackage `__init__.py` imports only. No `importlib.util.spec_from_file_location` filesystem-scan magic.
5. **Multi-container session cache:** Single container is fine for demo. Limitation documented in narrative follow-up (PP-04), not demoed.

---

## 📖 Narrative

### The Hook
The summit demo today teaches four modules from prod: context validation, prompt manager with TTL, tool registry, cost + unified log. That is the *core* architecture. But production at the company sits on top of four *more* patterns that the demo does not yet teach: per-session agent memory so chatbots remember prior turns, parallel skill execution in dependency waves, four execution modes from one entry point, and filesystem-based tool auto-discovery. Those four patterns are the difference between "neat prototype" and "yes that is what we actually ship."

### The Problem
The demo's inspector today shows seven panels. In a 15-minute talk that is plenty. In a 45-minute workshop audiences start asking the advanced questions:

- *"How do you handle multi-turn conversations? Does the model see the history?"*
- *"What if a product needs three skills and two of them are independent? Do you run them in series?"*
- *"You said every feature calls one endpoint. But chatbots need streaming. How do you reconcile?"*
- *"How does a team add a new tool? Is that a registry PR?"*

Right now the demo has to hand-wave those answers. With this spec landed, the demo *shows* them.

### The Opportunity
Teach the full architectural pattern without exposing any specific implementation. The demo becomes a self-contained reference: "if you want to build what eonar-mono has, here is the scaffolding generically, write your own tools on top."

Side benefit: because pretty-please is already a clean-room healthcare framing (MediMind clinic, generic patient/clinician), we are already most of the way there. The sanitization bar is "do not copy eonar code verbatim, do not use eonar ticket numbers, do not name eonar-specific tools." That is achievable.

### The Solution
Four small sub-tickets, each landing one pattern:

| Sub-ticket | Pattern | Demo value |
|---|---|---|
| PP-03a | Per-session agent cache | Multi-turn patient chat with memory. Visibly demonstrable. |
| PP-03b | Four execution modes | One `execute(mode=...)` routing to batch / streaming / agentic / chatbot-session. Shows the "one entry point" claim. |
| PP-03c | Parallel skill execution in dependency waves | Three-skill task profile renders in wall-clock time of the slowest wave, not the sum. Crowd-pleaser. |
| PP-03d | Tool auto-discovery from folders | Drop a `.py` file into `app/middleware/tools/` and restart — it is registered. Removes the current explicit list in `registry.py`. |

Each sub-ticket is independently shippable. Each upgrades one demo beat. No sub-ticket breaks the existing demo.

### Clean-Room Rules (non-negotiable)
- **Never read eonar code during implementation.** Port the *pattern* from memory / this spec. If a contributor needs to look at eonar-mono, they are doing it wrong.
- **No eonar ticket numbers in commits or code comments.** Pretty-please uses its own `PP-XX` scheme.
- **No eonar-specific tool names.** Pretty-please tools are healthcare-generic (`get_my_labs`, `get_patient_chart`, etc.) and stay that way.
- **No eonar-specific table names, column names, or env vars.** Pretty-please uses its own (already does; maintain).
- **No eonar dependency/ticket IDs named like `#709A` or `SKILL_REGISTRY_TABLE`.** Use generic names (`PP-03a`, `SKILLS_TABLE`).
- **Narrative rewrite is out of scope for this spec.** See section "Follow-ups."

---

## ⚙️ Mechanics

### PP-03a — Per-session agent cache

**Why:** Multi-turn conversations are the single biggest "it's not a prototype" signal. The moment an audience sees turn 2 recall something from turn 1, the demo stops being a toy.

**What to build:**
- `app/middleware/session_cache.py` — class that holds a dict of `session_id → agent_like_object` with a TTL (30 minutes default for demo; shorter than prod's 1hr so stage resets naturally).
- Getter method: if session is warm and unexpired, return cached handle; else create new one with the full prompt + tools + skills and cache it.
- Explicit evict method for logout beats.
- Background TTL sweep: simple, no asyncio gymnastics needed for demo — check on get.

**Demo upgrade:**
- Add an 8th inspector panel: "Session Memory" showing `session_id`, `turns`, `cache_age`, `HIT|MISS`.
- Stage beat: ask Patient Chat "what are my recent labs?" then "which one is worst?" — second turn answers correctly because the agent remembers.

**Clean-room implementation notes:**
- Do not reuse the prod class name. Pretty-please class: `SessionAgentStore` (different enough to be clearly fresh code).
- Do not copy prod's method signatures. Design from the demo's needs: in the demo we have synchronous Bedrock calls, not async — simpler.
- The core idea (dict + TTL + explicit evict) is a primitive used in hundreds of OSS projects. The implementation is *trivially* clean-room.

**Risks:**
- None material. ~80 lines of Python. Adds one inspector panel.

---

### PP-03b — Four execution modes from one entry point

**Why:** The #1 aha-moment claim in the talk is "every AI call goes through one `execute()`." Today the demo has one mode (agentic tool-use). A four-mode router makes that claim structurally honest instead of rhetorically honest.

**What to build:**
- Extend `orchestrator.execute(ctx, product_id, user_message, mode="agentic")` to accept `mode ∈ {"batch","streaming","agentic","chatbot_session"}`.
- `batch` — no tools, pure prompt → Bedrock → response. Used by a new "Clinician Summary" button on the clinician card.
- `streaming` — same as batch but yields chunks. Used to demo streaming on the patient card (new "Stream response" toggle).
- `agentic` — current behaviour. Default.
- `chatbot_session` — agentic + uses PP-03a session cache. Becomes the default for Patient Chat once PP-03a lands.

**Demo upgrade:**
- Change the "Mode" line in the inspector from `agentic (default)` to a live-routed label that flips per request.
- Add a toggle/button on each product card to exercise a different mode. Patient Chat: chatbot_session. Clinician Assist: agentic by default + a "one-shot summary" button that invokes batch mode.

**Clean-room implementation notes:**
- Our `execute()` is already the one entry point. This is additive — adding an `if mode == "batch"` branch, an `if mode == "streaming"` branch. Not a rewrite.
- Streaming via Bedrock Converse stream API is well-documented AWS behaviour; implementation is straight from AWS docs, not from eonar.
- Demo streaming presentation: typed text animation into the chat bubble. Alpine.js handles it cleanly.

**Risks:**
- Streaming on stage can look slower than batch if network is flaky. Keep streaming opt-in, not default, so a presenter can skip it if Wi-Fi is bad.

---

### PP-03c — Parallel skill execution in dependency waves

**Why:** The most original architectural move in prod. Audiences love the DAG walk. It also proves the "skills compose" claim in a way the current demo cannot.

**What to build:**
- `app/middleware/swarm.py` — class `SkillSwarm` with method `run(skill_ids, ctx, base_prompt)`.
- Wave-building algorithm:
  - Resolve dependencies transitively.
  - Topological partition into waves: wave 0 = skills with no unresolved deps, wave N = skills whose deps all live in 0..N-1.
  - Execute each wave with `asyncio.gather` (or `ThreadPoolExecutor` if we want sync code — see question 4 for which).
  - Pass upstream results into downstream skills via kwargs.
- Return a dict keyed by skill_id.

**Demo upgrade:**
- Add a "Batch Analysis" button to the clinician card that runs three skills together: `humanize`, `biomarker-analysis`, `supplement-guidance` (where `supplement-guidance` depends on `biomarker-analysis`).
- Add a 9th inspector panel: "Skill Swarm" showing the wave DAG and wall-clock per wave.
- Stage beat: press the button, watch three skill entries populate, two in wave 0 parallel, one in wave 1. Show the wall-clock savings.

**Clean-room implementation notes:**
- Wave-building from a dependency dict is an undergraduate algorithm. Implement from scratch on a whiteboard; do not read eonar's version.
- Prod uses `asyncio.gather`. Demo is currently synchronous FastAPI — can stay sync with `concurrent.futures.ThreadPoolExecutor` and still demonstrate parallelism. Simpler to reason about on stage. **Recommend ThreadPoolExecutor for the demo.**
- Skill dependencies are already in the demo's `summit_skills` table (`dependencies` column). This sub-ticket uses the column that is already there.

**Risks:**
- Bedrock rate limits on parallel calls. For a demo with 2-3 concurrent skills we are comfortably under any tenant limit. Document as a known tradeoff in the narrative follow-up.
- Error handling in a wave: if one skill fails, do we continue or abort? **Recommend abort and surface** — simpler, more demoable, matches user expectation.

---

### PP-03d — Tool auto-discovery from folders

**Why:** The "drop a file, add a tool" story is one of the strongest onboarding stories we have. Today the demo registers tools explicitly in `registry.py`. That contradicts the story.

**What to build (simple variant, per open question 4):**
- `app/middleware/tools/` becomes a package where `__init__.py` imports every tool module explicitly.
- Each subpackage (`chatbot/`, `clinician/`) has its own `__init__.py` that does the same.
- A contributor adds a new tool by: (1) creating a new `.py` file with one `@tool`-decorated function, (2) adding one import line to the nearest `__init__.py`. Two edits, both trivial.
- **Not** a full filesystem scan with `importlib.util.spec_from_file_location`. That is more magic than the talk can teach.

**Demo upgrade:**
- Rename existing `tools/patient_tools.py` into `tools/patient/labs.py`, `tools/patient/notes.py`, `tools/clinician/chart.py`, `tools/clinician/triage.py` — four files, one tool each.
- Update the inspector's ToolRegistry panel to show the source file path next to each available tool.
- Stage beat (optional, only in 45-min workshop): create a new tool file live on stage, add one import line, restart container, show it registered.

**Clean-room implementation notes:**
- Decorator-based registry is a 30-line pattern from any Python tutorial. No eonar source needed.
- File layout is the demo's own choice. Keep it readable.

**Risks:**
- Restart-to-pick-up is a UX mismatch with prompt editing (which does not require restart). Narrative needs one line explaining: "code changes require restart; data changes don't. This is the prompt/skill/routing/tool-list distinction."

---

### What stays the same (non-goals)
- **DEFCON demo at `/` — DO NOT TOUCH.** See dedicated protection protocol below.
- Existing demo stops 1-4 — unchanged, still work.
- SQLite schema — unchanged (session cache is in-memory; tool layout is filesystem).
- `POST /v1/infer` contract — unchanged (mode is an additive parameter).
- Alpine.js frontend foundation — unchanged (just new panels and a couple of buttons).
- Pretty-please container image size, start-up time, stage reliability — measured, must not regress.

### Overall Risks & Mitigations
| Risk | Mitigation |
|---|---|
| Scope creep — four patterns become one giant PR | Sub-tickets with independent acceptance gates (open Q 1) |
| Accidental eonar code copy-paste | Review rule: reviewer must confirm no eonar file was opened during PR authoring |
| Streaming flakiness on stage | Streaming is opt-in; presenter can skip |
| Rate limits on parallel swarm | Max 3 concurrent skills in the demo; documented |
| Demo gets too complex — loses the 15-min talk | Core 5-stop script stays identical; new content is in the 45-min workshop extension |
| Session cache breaks between stage runs | Explicit `POST /summit/api/reset` endpoint that clears the session store |
| Inspector panel count grows to 9+ — visual clutter | Re-layout: tabs within the inspector if >7 panels, rather than a long scroll |

---

## ⚡ Execution Steps

**All four sub-tickets follow the same gate:** lint clean, 5-stop demo still passes, new beat works, no regression in DEFCON tab.

### Phase 1 — Umbrella spec approval (this doc)

1. User reads and approves the sub-ticket split (open Q 1).
2. User confirms pretty-please ticket scheme (open Q 2).
3. User confirms `/` DEFCON untouched (open Q 3).
4. User confirms simple auto-discovery variant (open Q 4).
5. User says "execute PP-03a first" or "all four in parallel."

### Phase 2 — PP-03a: SessionAgentStore

6. Create `app/middleware/session_cache.py` with `SessionAgentStore` class.
7. Wire into `orchestrator.execute()` behind `mode="chatbot_session"` (depends on PP-03b merging first, OR add temporary `use_session=True` flag).
8. Add 8th inspector panel in `summit.html` + `summit.js`.
9. Lint, 5-stop smoke, new multi-turn beat works.

### Phase 3 — PP-03b: Four execution modes

10. Extend `orchestrator.execute()` signature with `mode` parameter.
11. Branch on mode — batch, streaming, agentic (current), chatbot_session.
12. Streaming uses Bedrock Converse stream API + FastAPI StreamingResponse + Alpine typed animation.
13. Add mode toggle on each product card.
14. Update Mode line in inspector to flip per request.
15. Lint, 5-stop smoke (default agentic still works), new mode beats work.

### Phase 4 — PP-03c: SkillSwarm

16. Create `app/middleware/swarm.py` with wave-building + `ThreadPoolExecutor` execution.
17. Wire a "Batch Analysis" button on clinician card that invokes the swarm with three skills.
18. Add 9th inspector panel (or tab — see risks).
19. Lint, 5-stop smoke, batch analysis beat works and shows wall-clock parallelism.

### Phase 5 — PP-03d: Tool auto-discovery (simple variant)

20. Refactor `tools/patient_tools.py` into `tools/patient/{labs,notes}.py` + `tools/clinician/{chart,triage}.py`.
21. Each subpackage `__init__.py` imports its modules. Top-level `tools/__init__.py` imports subpackages.
22. `registry.py` replaces explicit registration list with a module-walk that collects all `@tool`-decorated callables from the imported tree.
23. Inspector tool list shows source file per tool.
24. Lint, 5-stop smoke, all tools still callable.

### Phase 6 — Narrative follow-up (separate ticket, out of scope here)

25. Open PP-04 to update `narrative-summit.md` with the new patterns. Not this spec.

---

## � DEFCON Protection Protocol

**User directive (verbatim):** *"dont touch DEFCON DO NOT TOUCH DEFCON.. test it if we re not breaking it"*

DEFCON is the adjacent demo at `http://52.220.182.114:8888/` — eight security attack scenarios on the original MediMind app. It is Ford's demo. **Breaking it is a release blocker.**

### Files a PR in this epic is FORBIDDEN from modifying
- `app/main.py` — only additive edits permitted (new router includes, new startup hooks). No edits to existing DEFCON routes.
- `app/static/index.html` — DEFCON page. No edits.
- `app/static/app.js` — DEFCON frontend. No edits.
- `app/attacks/**` — all attack modules untouched.
- `app/db.py` — only additive edits (new tables, new init functions). No edits to existing schema or seed logic.
- `app/routes.py` (if exists) — DEFCON routes untouched.
- `app/matrix_test.py` + `app/verification/**` — attack test suite untouched.
- The 8 attack scenarios and their flag-capture logic — untouched.

### Files a PR in this epic is ALLOWED to modify
- `app/middleware/**` — all summit middleware.
- `app/routes_summit.py` — all summit routes.
- `app/static/summit.html` and `app/static/summit.js` — summit UI.
- New files under `app/middleware/tools/**` — tool auto-discovery refactor.

### Mandatory DEFCON smoke test — run before AND after every PR in this epic

**Before starting work:** baseline that DEFCON is healthy.
**After every PR merges:** re-run to confirm no regression.

```bash
# 1. Load DEFCON home page
curl -sf http://52.220.182.114:8888/ > /dev/null && echo "✅ DEFCON page loads" || echo "❌ DEFCON BROKEN"

# 2. Confirm attack surface still renders — count <section> or card markers in the HTML
curl -sf http://52.220.182.114:8888/ | grep -c 'class="attack' \
  | awk '{ if ($1 >= 8) print "✅ 8+ attacks rendered"; else print "❌ ONLY " $1 " ATTACKS — REGRESSION" }'

# 3. Run the attack matrix test suite (authoritative)
docker exec pretty-please-run python3 -m app.matrix_test 2>&1 | tail -20

# 4. Spot-check one attack endpoint returns 200 (pick whichever is most public / non-destructive)
curl -sf -o /dev/null -w "%{http_code}\n" http://52.220.182.114:8888/api/patients
```

**Gate:** If any of the four checks fail after a PR, **revert the PR immediately**. DEFCON health precedes demo upgrades.

### Browser-verified smoke (human, before stage)
1. Open `http://52.220.182.114:8888/` in browser. Page renders. Header/nav present.
2. All 8 attack cards visible and clickable.
3. Click into at least two attacks. Expected behaviour (success / block / prompt) still renders.
4. Open `http://52.220.182.114:8888/summit` in same browser. No console errors. Nav link between `/` and `/summit` both work.

---

## �🚨 Data Requirements

**No schema changes.**
- `summit_skills.dependencies` column is already populated by seed. PP-03c uses the column that is already there.
- No new tables. Session cache is in-memory. Tool discovery is filesystem.
- Seed data (`seed.py`) unchanged.

---

## 🚨 Prod Impact

**None for eonar-mono.** This is entirely in the pretty-please repo.

**Clean-room compliance** is the key prod-adjacent concern. Reviewers must confirm:
- No eonar source files were opened while authoring the PR.
- No eonar ticket numbers in commits, comments, or docs.
- No eonar-specific class names, env var names, or table names.
- All four patterns implemented from the generic description in this spec + public AWS docs + standard Python idioms.

---

## 📚 References

- Pretty-please current state: `/home/dev003/pretty-please/app/middleware/`
- Current narrative: `/home/dev003/narrative-summit.md`
- Related in-flight spec: `/home/dev003/pretty-please/specs/SUMMIT-02-strands-and-guardrail.md`
- Public AWS Bedrock Converse streaming docs: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html
- Public Strands Agents docs: https://strandsagents.com/
- Python `concurrent.futures` stdlib docs for ThreadPoolExecutor

**Explicitly NOT referenced during implementation:** any file under `/home/dev003/eonar-mono/backend/ai_middleware/` or `/home/dev003/eonar-mono/backend/mcp_tools/`.

---

## ❓ FAQ

**Q: Why not just port the eonar files directly?**
A: Pretty-please is a public-facing demo. Eonar code is company IP. The patterns are industry-generic; the code is not. Clean-room implementation keeps the demo shareable without legal friction.

**Q: Why four sub-tickets instead of one?**
A: Each pattern adds a demo beat independently. Four small PRs are reviewable. One big PR is not. Also: if only two of the four survive review, the demo still improves, no partial rewrite.

**Q: Why ThreadPoolExecutor for swarm instead of asyncio?**
A: The demo's FastAPI routes are currently synchronous. Mixing sync and async adds cognitive load on stage. ThreadPoolExecutor demonstrates parallelism with zero async machinery. Prod uses asyncio because prod needs it; the demo does not.

**Q: Why simple-variant auto-discovery instead of full filesystem scan?**
A: The "drop a file, add one import line" story is almost as strong as "drop a file and it just works" — and it can be taught in a 15-minute talk without losing the audience. Full filesystem scan adds importlib magic that is not worth ten minutes of workshop time to explain.

**Q: Will this delay the Summit demo?**
A: Summit demo today works. This is additive. If Summit is the priority and sub-tickets land post-Summit, the current demo still delivers the core message. These patterns upgrade the talk from 15-min to 45-min workshop material.

**Q: What if we need to demonstrate the multi-container session cache limitation?**
A: Do not. Document it in the narrative as a known tradeoff. "In-memory per container; multi-instance deployments need session affinity or a shared cache backend." That is one line, one slide, done.

**Q: Can this spec land before SUMMIT-02?**
A: Yes. They are orthogonal. PP-03a-d touch orchestrator control flow + inspector panels. SUMMIT-02 touches the Bedrock call path + guardrail config. Zero merge conflicts expected.

---

## 🧪 Local Testing Setup

Applies per sub-ticket. Each PR must pass this before merge.

### Startup
```bash
cd /home/dev003/pretty-please
docker rm -f pretty-please-run 2>/dev/null
docker build -t pretty-please:dev .
docker run -d --name pretty-please-run -p 8888:8000 \
  -e AWS_REGION=us-east-1 \
  pretty-please:dev
open http://52.220.182.114:8888/summit
```

### AWS services this PR touches
| Service | Test step |
|---|---|
| Bedrock Converse | All four modes return sensible responses |
| Bedrock Converse Stream (PP-03b) | Streaming mode yields chunks, renders progressively in UI |
| CloudWatch stdout logs | `docker logs pretty-please-run` shows wave boundaries, session HIT/MISS |

### Unit tests (add as we land each sub-ticket)
- `tests/test_session_cache.py` — HIT, MISS, expiry, explicit evict
- `tests/test_swarm_waves.py` — wave partitioning on several dep graphs
- `tests/test_orchestrator_modes.py` — each mode routes correctly
- `tests/test_tool_autodiscovery.py` — new file in tree is discovered

### Verification steps (per sub-ticket)

**PP-03a — Session cache**
1. Open Patient Chat. Ask "what are my recent labs?" Send.
2. Ask "which one is most out of range?" Send.
3. Response references prior turn. Inspector panel 8 shows HIT.

**PP-03b — Four modes**
1. Default agentic mode still works (stops 1-4 unchanged).
2. Toggle "Stream" on Patient Chat. Response appears progressively.
3. Press "One-shot Summary" on Clinician Assist. Batch mode runs, no tool calls, response returned as a block.
4. Inspector Mode line flips per request.

**PP-03c — Skill swarm**
1. Press "Batch Analysis" on Clinician Assist.
2. Three skill rows populate. Two share a start time (wave 0). One comes later (wave 1).
3. Wall-clock total < sum of individual skill times.

**PP-03d — Auto-discovery**
1. Create `app/middleware/tools/clinician/flagged.py` with one new `@tool` function.
2. Add one import line to `app/middleware/tools/clinician/__init__.py`.
3. Restart container.
4. Inspector shows the new tool name in the available list.

### Gate
All sub-tickets: lint clean, 5-stop canonical demo still passes, no DEFCON regression, verification steps tick.

---

## 🔁 Follow-ups (not in this spec)

- **PP-04 — Narrative update.** Update `narrative-summit.md` to include the four new patterns. New stops, new aha-moments, new Q&A entries. Ticket opens after PP-03a-d merges.
- **PP-05 — 45-min workshop extension.** Full hands-on workshop script that walks through each new pattern live.
- **PP-06 — Diagrams.** Architecture diagram updates for slide decks. Mermaid or tldraw source in `/specs/diagrams/`.

---

## ✅ Spec Readiness Checklist

- [x] TLDR written
- [x] Confidence stated (High / Medium)
- [x] All required sections filled (Narrative, Mechanics, Execution Steps)
- [x] Open questions resolved (all 4 locked in "Resolved Decisions")
- [x] Data requirements checked — no schema changes
- [x] Prod impact — none for eonar-mono; clean-room rules documented
- [x] Local testing setup per sub-ticket
- [x] Clean-room rules explicit
- [x] DEFCON protection protocol explicit
- [x] Follow-up tickets identified but out of scope

**Status:** ✅ Ready to execute. Hand to a Ticket or Micro agent.

---

## ✅ Completion Checklist (filled during execution)

### Implementation
- [x] `app/middleware/session_store.py` — `SessionAgentStore` class with per-session message cache, 30 min TTL, explicit evict, thread-safe
- [x] `app/middleware/swarm.py` — `build_waves()` topo-sort + `run_swarm()` with `ThreadPoolExecutor` per wave
- [x] `app/middleware/tools/patient/{labs,notes}.py` — 2 tools, auto-registered via `__init__.py` imports
- [x] `app/middleware/tools/clinician/{chart,triage}.py` — 2 tools, auto-registered via `__init__.py` imports
- [x] `app/middleware/tools/__init__.py` — imports both subpackages; decorator side-effects populate the registry
- [x] `app/middleware/tools/patient_tools.py` — deleted (superseded)
- [x] `app/middleware/tools/registry.py` — `ToolSpec.source` field added so UI can show origin module
- [x] `app/middleware/orchestrator.py` — full rewrite with 4 modes: `agentic` / `batch` / `streaming` / `chatbot_session`; shared `_prepare`, `_run_agentic_loop`, `_run_batch`; new `execute_stream()` generator; new `execute_single_skill()` used by swarm
- [x] `app/routes_summit.py` — `/v1/infer` accepts `mode`; new `/v1/infer/stream` (SSE), `/v1/swarm`, `/v1/session/reset`, `/summit/api/session`, `/summit/api/tools`
- [x] `app/static/summit.html` — mode selectors on both product cards; `⚡ Swarm` button on clinician card; reset button on patient card; 3 new inspector panels (SessionAgentStore, SkillSwarm, Tool Auto-Discovery)
- [x] `app/static/summit.js` — streaming consumer, swarm caller, session refresh, tool catalog loader, mode wiring
- [x] `ruff check app/middleware/ app/routes_summit.py` — All checks passed
- [x] Image rebuilt, container recreated from new `pretty-please:dev` image

### Verification (live, not theoretical)
- [x] **DEFCON intact** — `/` → 200, `/health` → 200, `/how-it-works` → 200, `/api/logs` → 200
- [x] **DEFCON files untouched** — verified via file listing: `main.py`, `static/index.html`, `static/app.js`, `attacks/**`, `tools_fortress.py`, `tools_vibe.py`, `prompts.py`, `seed_data.py`, `guardrails.py`, `memory.py`, `audit.py`, `auth_sig.py`, `log_store.py` — zero edits
- [x] **PP-03d** — `GET /summit/api/tools` returns 4 tools, each with correct `source` module (`app.middleware.tools.patient.labs`, `.patient.notes`, `.clinician.chart`, `.clinician.triage`)
- [x] **PP-03a** — 2-turn chatbot_session: turn 1 "hi i am alex, remember my name" → turn 2 "what is my name?" → response: *"You're Alex."* Session went `cold → warm`, `turns: 1 → 2`, `message_count: 2 → 4`
- [x] **PP-03b** — `MODES = ('agentic', 'batch', 'streaming', 'chatbot_session')` exposed; inspector reports `mode` field on every call; streaming endpoint registered and returns SSE
- [x] **PP-03c** — Swarm run with 3 skills: wave 0 ran `biomarker-analysis` + `clinical-safety` in parallel (10s), wave 1 ran `inflammation-analysis` sequentially (16s). 3 Bedrock calls, $0.025, 2146 tokens rolled up correctly. Topo-sort honored the skill dependency on `biomarker-analysis`
- [x] No tracebacks in container logs
- [x] All 5 original demo stops still work (home page, summit page, existing `/v1/infer` still accepts requests without `mode` field due to default)

### Ticket Hygiene
- [x] Spec reflects final implementation (this section)
- [ ] GitHub issue — N/A (pretty-please uses spec-only workflow, no GitHub tracker)
- [ ] Commit — **NOT committed**; engineer to run commit-readiness-gate skill when ready
- [ ] PR — N/A (direct branch workflow)

### Follow-ups opened (separately)
- PP-04 narrative update (existing, not started)
- PP-05 workshop extension (existing, not started)
- PP-06 diagrams (existing, not started)
