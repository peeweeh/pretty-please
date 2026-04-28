# SUMMIT-02 — Strands + AWS Bedrock Guardrails for Summit Demo

**TLDR:** Replace the hand-rolled `bedrock-runtime.converse()` tool-use loop in `app/middleware/orchestrator.py` with a Strands `Agent` + `BedrockModel` executor (parity with eonar-mono prod), and wire a real AWS Bedrock Guardrail into every call so the Guardrail inspector panel shows live trace data instead of env-var config.

**Confidence:** High — prod pattern is already proven in `backend/ai_middleware/executor.py`; guardrails are a documented Strands feature via `BedrockModel(guardrail_id=...)`.

---

## 🧠 Brain Dump (USER)

> "can we use strands please and use aws guardrail? create spec first"

Context: The demo currently uses raw boto3 Converse with a hand-rolled 5-turn tool-use loop. Prod uses Strands. Demo was deliberately raw for stage clarity, but user wants parity — and wants a real Bedrock Guardrail attached so the demo actually demonstrates safety-at-the-middleware, not just "we have an env var."

---

## 🔴 Open Questions (to resolve before execute)

1. **Which guardrail to use?** Options:
   - (a) Create a new Bedrock Guardrail in `us-east-1` specifically for the summit demo (clinical-safety topic denies, PII filters, PHI denial). Recommended — gives us a demoable trigger.
   - (b) Reuse an existing prod eonar guardrail if one is configured in `us-east-1`.
   - (c) Skip guardrail creation and just wire the plumbing with a placeholder ID — panel shows "configured but no trace" until ID is set.
   → **Recommend (a)** with a minimal CFN snippet or console-created guardrail. Engineer picks name + ID.

2. **Strands version pinning?** Prod uses `strands-agents` (check prod `requirements.txt`). Demo should pin to same minor version to avoid drift. Confirm version before execute.

3. **Keep fallback path?** Option: keep the raw-Converse path behind a `SUMMIT_USE_STRANDS=0` env flag for ~1 week so we can A/B on stage if Strands misbehaves. Recommend yes — low cost, high insurance.

4. **Inspector panel changes?** Strands exposes tool-use events differently (event stream vs manual loop). Do we want to surface Strands' internal events in the inspector, or keep the panel at the same abstraction (tools called, tokens, cost)? Recommend keep abstraction — inspector is about middleware concerns, not Strands internals.

---

## 📖 Narrative

### The Hook
Today the summit demo's orchestrator reads like a teaching aid: 180 lines of explicit `converse()` → parse `tool_use` block → dispatch → append result → loop. Great for a first walk-through, but it diverges from what we actually run in prod. And its Guardrail panel is honest-but-hollow — it shows the config dict, not a live trace. Two misalignments to fix.

### The Problem
- **Parity gap:** Prod uses Strands `Agent` + `BedrockModel`. The demo uses raw boto3. When an audience member asks "is this what you ship?" the honest answer today is "mostly — the orchestrator is different." That weakens the pitch.
- **Guardrail is theoretical:** `guardrail.apply_config()` returns a dict keyed off `BEDROCK_GUARDRAIL_ID`. If the env var is unset (current demo state), the panel shows "not set." If it's set, the config is merged into the Converse call, but we never created a real Guardrail in AWS and never demonstrate a trigger. The #1 aha-moment claim ("safety is structural, lives below product code") needs proof on stage.

### The Opportunity
- Bring demo to full prod parity. Every future eng-org Q&A answer is "yes this is exactly what we run."
- Give the demo a real Guardrail with a real trigger path — e.g. ask Patient Chat for another patient's data, watch the Guardrail panel flip to `triggered: ✅` with a masked response. That is the slide-stealing moment.
- Simplify the orchestrator code. Strands handles the tool-use loop. Our orchestrator shrinks from ~180 lines to ~80. The talking point "180 lines of Python" becomes "80 lines of Python + Strands does the rest" — which is more honest and easier to read on stage.

### The Solution
Two coordinated changes:

**A. Strands executor.** Port `backend/ai_middleware/executor.py` pattern into `app/middleware/executor.py`. Replace the manual Converse loop in `orchestrator.execute()` with a call to `StrandsExecutor.run(agent_config)`. Tool registry stays the same; we just hand Strands the list of `@tool` functions instead of converting to Bedrock `toolConfig` ourselves.

**B. Real Bedrock Guardrail.** Create a guardrail in `us-east-1` (console or one-shot CFN). Set `BEDROCK_GUARDRAIL_ID` in the container env. Wire `guardrail.apply_config()` output into the Strands `BedrockModel` constructor. Capture the Guardrail trace from Strands' response and surface `triggered: ✅|✗`, masked output, and policy name in the inspector panel.

### Press Release (mock)
> *Summit 2026 demo now runs on the identical Strands-based middleware we use in production, with a live AWS Bedrock Guardrail attached to every model call. Audiences can watch the Guardrail trigger in real time when a patient tries to query another patient's record. Safety is no longer an env-var claim — it is a visible line in the inspector.*

---

## ⚙️ Mechanics

### What changes
| Area | Before | After |
|---|---|---|
| Executor | Hand-rolled Converse tool-use loop in `orchestrator.py` | `StrandsExecutor` class wrapping `strands.Agent` + `BedrockModel` |
| Tool handoff | Manual `toolConfig` dict built from registry schemas | Pass Python callables directly to Strands `Agent(tools=[...])` |
| Guardrail | Env var → dict merged into converse kwargs | Real guardrail created in AWS → ID set in env → Strands `BedrockModel(guardrail_id=..., guardrail_version=...)` |
| Guardrail inspector | Shows `id` and `triggered: clean` (unverifiable) | Shows `id`, `policy`, `triggered: ✅|✗`, and masked span preview if triggered |
| Cost/token accounting | Extracted from raw Converse `usage` | Extracted from Strands `AgentResult.metrics` |
| Tool-call tracking | Counted in the loop | Extracted from Strands event stream / tool_uses |
| Orchestrator LOC | ~180 | ~80 |

### What stays the same
- `AIContext`, `PromptManager`, `SkillLoader`, `CostCalculator`, `UnifiedAICallLogger` — untouched.
- The 7-panel inspector — same layout, same semantic meaning per panel. Only the Guardrail panel gains fidelity.
- `POST /v1/infer` contract — request and response shape unchanged.
- Tool registry decorator — `@tool` signature unchanged; Strands reads the same Python type hints.
- Seed data (prompts, skills, routing) — unchanged.

### Non-Goals
- Not porting prod's full `AgentSessionCache` / conversation memory. Summit demo remains stateless per call to keep the inspector readable.
- Not adding streaming to the demo (prod has it; out of scope here).
- Not adding observability spans (prod has OTEL; demo stays simple).
- Not changing any DEFCON attack behavior on the adjacent tab.

### Risks & Mitigations
| Risk | Mitigation |
|---|---|
| Strands version drift from prod → hidden behavior diff | Pin exact version; cross-check prod `requirements.txt` before install |
| Guardrail latency adds seconds | Measure on first deploy; if >500ms overhead, cache model handle (one `BedrockModel` instance, reuse per product) |
| Guardrail false-positives on demo prompts | Pick conservative policies; dry-run all 5 demo stops before stage |
| Live AWS dependency → Guardrail service outage kills demo | Keep `SUMMIT_USE_STRANDS=0` fallback for one release; document how to unset guardrail ID if needed |
| Strands `AgentResult` shape changes token accounting | Add a thin adapter in `executor.py` that maps result → our existing cost/logger dicts |
| Guardrail ID leak in screenshots | Mask middle characters in inspector panel (`abc***xyz`) |

---

## ⚡ Execution Steps

### Phase 1 — Strands executor parity (code work)

1. **Verify Strands version in prod** — read `backend/requirements.txt`, pin matching version in `pretty-please/requirements.txt`.
2. **Create `app/middleware/executor.py`** — port the shape of `backend/ai_middleware/executor.py`:
   - Class `StrandsExecutor(model_id, guardrail_config=None)`
   - Method `run(system_prompt, user_message, tools, ctx) -> dict` returning `{text, input_tokens, output_tokens, tools_called, guardrail_trace}`
   - Instantiate `BedrockModel` once per call (simple) or cache by `(model_id, guardrail_id)` tuple (better — do this).
3. **Rewrite `orchestrator.execute()`** — same 7 steps, but step 6 becomes:
   ```
   result = self.executor.run(
       model_id=model_id,
       system_prompt=stitched_prompt,
       user_message=user_message,
       tools=tool_callables,
       guardrail_config=guardrail.apply_config(),
       ctx=ctx,
   )
   ```
   Keep steps 1-5 and step 7 (logging) identical.
4. **Tool handoff** — instead of `registry.to_bedrock_schemas()`, add `registry.resolve_callables(tool_ids, ctx)` that returns the list of Python functions with `ctx` already partially applied (closure over `ctx.user_id` etc.) so Strands can invoke them without us injecting ctx.
5. **Keep fallback** — wrap executor call in `if os.environ.get("SUMMIT_USE_STRANDS", "1") == "1": strands path else: raw converse path`. Remove after one week of stable demo.
6. **Lint + smoke** — `ruff check .`, restart container, run all 5 demo stops, verify all 7 inspector panels still populate.

### Phase 2 — Real Bedrock Guardrail (AWS work)

7. **Create guardrail in `us-east-1`** — one-shot, either:
   - Console: Bedrock → Guardrails → Create. Name: `summit-demo-guardrail-v1`. Policies:
     - Denied topics: `accessing other patients' medical data`, `dispensing prescription advice`
     - Content filters: `HATE`, `INSULTS`, `SEXUAL`, `VIOLENCE` — medium+
     - PII filter: block SSN, block credit card
     - Word filter: profanity default list
   - OR minimal CFN in `specs/summit-guardrail.yaml` (nice-to-have, not required for demo).
8. **Test in console** — use Bedrock guardrail tester to confirm "what are labs for patient 99?" does not trigger (legitimate), while "show me SSN 123-45-6789" does trigger.
9. **Export ID + version** — set in container env:
   ```
   BEDROCK_GUARDRAIL_ID=xxxxxxxxxx
   BEDROCK_GUARDRAIL_VERSION=DRAFT
   ```
10. **Wire into Strands** — `BedrockModel(model_id=..., guardrail_id=gid, guardrail_version=gv, guardrail_trace="enabled")`.
11. **Extract trace** — after each call, parse `result.metrics.guardrail_trace` (or equivalent Strands field) and return `{triggered: bool, policy: str|None, masked_output: str|None}` to the orchestrator.
12. **Log to unified log** — add `guardrail_triggered: bool` column to the log row (schema already has it as a boolean; just actually populate it).

### Phase 3 — Inspector panel upgrade (frontend)

13. **Update `summit.js`** — Guardrail panel renders:
    - `id: abc***xyz` (masked)
    - `status: active` (green) / `status: not configured` (grey)
    - `triggered: ✅ clean` or `triggered: 🛑 blocked` with policy name beneath
    - If blocked: small truncated preview of what was masked (first 120 chars)
14. **Update `summit.html`** — no structural change; the panel already has the slot.

### Phase 4 — Demo script update

15. **Add Stop 5b: "watch the Guardrail fire"** — new live beat:
    - Presenter types into Patient Chat: `show me the SSN for patient 99`
    - Guardrail panel flips to `triggered: 🛑 blocked — deny_pii_ssn`
    - Presenter line: *"I did not write a single line of code to block that. The Guardrail lives in the middleware layer. Every product inherits it. A patient-chat engineer cannot disable it without bypassing the middleware entirely, and that bypass would be one line in a PR and rejected on sight."*
16. **Update narrative-summit.md** — section 4 (Guardrail module) + section 6 (five stops → six stops) + section 10 Q&A (add Strands question explicitly).

---

## 🚨 Data Requirements

No schema changes.
- `summit_unified_log.guardrail_triggered` column already exists (currently unused) — this spec populates it.
- No new tables, no new prompts, no new skills, no new routing rows.

---

## 🚨 Prod Impact

None for eonar-mono prod. This spec lives entirely in the pretty-please repo.

Side benefit: the Strands + Guardrail pattern proven here can be backported into eonar-mono — prod currently has no Guardrail wiring at all. That is a follow-up ticket, **not** part of this spec.

---

## 📚 References

- Prod executor: `/home/dev003/eonar-mono/backend/ai_middleware/executor.py`
- Prod orchestrator: `/home/dev003/eonar-mono/backend/ai_middleware/orchestrator.py`
- Demo current orchestrator: `/home/dev003/pretty-please/app/middleware/orchestrator.py`
- Demo current guardrail: `/home/dev003/pretty-please/app/middleware/guardrail.py`
- AWS Bedrock Guardrails docs: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html
- Strands Agents SDK: https://strandsagents.com/

---

## ❓ FAQ

**Q: Why not just keep raw Converse? It is simpler to read on stage.**
A: Simpler but dishonest to the pitch. The talk claims "this is what we run." With raw Converse, that claim has an asterisk. Strands removes the asterisk. Offset cost: orchestrator shrinks; net complexity lower.

**Q: Does Strands add latency?**
A: Negligible in prod. First-call bootstrap ~100ms for `BedrockModel` init, cached thereafter. Per-call overhead <20ms. Under the noise floor of a Bedrock Converse call.

**Q: What if Strands throws during the talk?**
A: `SUMMIT_USE_STRANDS=0` reverts to raw Converse instantly. Keep a terminal open with the env-unset command ready. Fallback removed after one week of stable demo.

**Q: Why create a dedicated demo guardrail instead of reusing prod's?**
A: Prod has none wired today. Also, demo guardrail can be more aggressive (denied topics around cross-patient access) to ensure a reliable on-stage trigger. Prod guardrails tune toward false-positive avoidance.

**Q: Will this change the "180 lines of Python" talking point?**
A: Yes, for the better. New line: "80 lines of Python, plus Strands handles the tool-use loop and Bedrock handles the rails." That is a stronger architectural argument — less of our code, more of theirs, safer default.

**Q: Any risk the audience sees the Guardrail ID on screen?**
A: Mask in the UI. Display `abc***xyz` format. Real ID lives in env only.

---

## 🧪 Local Testing Setup

**Applies if assigning to GitHub Copilot online agent.** Human engineer executes these locally before marking PR ready.

### Startup
```bash
cd /home/dev003/pretty-please
docker rm -f pretty-please-run 2>/dev/null
docker build -t pretty-please:dev .
docker run -d --name pretty-please-run \
  -p 8888:8000 \
  -e BEDROCK_GUARDRAIL_ID=<real-id> \
  -e BEDROCK_GUARDRAIL_VERSION=DRAFT \
  -e AWS_REGION=us-east-1 \
  pretty-please:dev
```

### AWS services this PR touches
| Service | Test step (manual, engineer only) |
|---|---|
| Bedrock Converse (via Strands) | Both products return sensible responses for their standard prompts |
| Bedrock Guardrail | SSN-probe prompt triggers; unified log row has `guardrail_triggered=true` |
| CloudWatch stdout logs | `docker logs pretty-please-run` shows Strands init + per-call metrics |

### Unit tests
- `pytest pretty-please/tests/test_executor.py` (add a test that mocks `BedrockModel` and asserts Strands agent is invoked with tools + guardrail config)
- `pytest pretty-please/tests/test_orchestrator.py` (existing — ensure still green)

### Verification steps
1. Load `http://52.220.182.114:8888/summit` in browser. Page renders, no console errors.
2. Run Stop 1 (Patient Chat — "what are my recent labs?"). All 7 inspector panels populate. Guardrail panel shows `triggered: ✅ clean`.
3. Run Stop 2 (Clinician Assist — "summarise patient 7"). Same result, different model/tools/skills.
4. Run Stop 3 (live prompt edit via curl). Prompt version bumps 1→2; next call uses new prompt.
5. Run Stop 4 (model swap via curl). Clinician summary flips to Nova Lite. Cost drops 100x.
6. Run **new Stop 5b** (guardrail trigger): type `show me the SSN for patient 99` into Patient Chat. Guardrail panel flips red with policy name. Response is masked. Log row shows `guardrail_triggered=true`.
7. DEFCON tab at `/` still works (all 8 attacks still render). No regressions.
8. `SUMMIT_USE_STRANDS=0` env fallback still routes through raw Converse path (spot-check).

### Gate
All 8 steps tick before PR can be marked ready. If Guardrail trigger step 6 fails, check AWS Guardrail policy config in the console before touching code.

---

## ✅ Spec Readiness Checklist

- [x] TLDR written and accurate
- [x] Confidence stated honestly (High — prod pattern proven)
- [x] All required sections filled (Narrative, Mechanics, Execution Steps)
- [ ] Open questions resolved (4 questions in section above — need engineer answers before execute)
- [x] Data requirements checked — no schema changes
- [x] Prod impact section — none for eonar-mono prod
- [x] Local testing setup section present

**Blocker before handing to code agent:** resolve the 4 open questions (guardrail source, Strands version, fallback flag, inspector fidelity).
