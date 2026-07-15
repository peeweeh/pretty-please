# The 15-Minute Story — "Everyone's Vibe-Coding Agents"

**What this doc is:** everything you need to build the deck. Slide-by-slide text,
speaker notes, exact click-by-click demo cues, timing, and backup screenshots
(in `docs/images/`) for when conference wifi eats the live demo.

**Thesis, one line:** *Architecture answers "who's allowed to touch this."
It doesn't answer "what did they actually say." You need both, and both are
cheaper than you think.*

**Format:** DEFCON-style cold open → live-fixed architecture ladder → the
payoff (speed, tracing, content-level guardrails). One continuous story, one
tab (`/summit2`), not three separate demos bolted together.

---

## Timing map (15 min total)

| Time | Section | Slide(s) |
|---|---|---|
| 0:00–0:45 | Cold open | 1 |
| 0:45–1:30 | Thesis | 2 |
| 1:30–5:30 | Act 1 — Vibe-coded | 3–4 |
| 5:30–9:30 | Act 2 — Fix it, cheapest first | 5–6 |
| 9:30–11:30 | Act 3 — Fast + traced | 7 |
| 11:30–13:30 | Act 4 — Content guard | 8 |
| 13:30–15:00 | Close + CTA | 9 |

**9 slides for 15 minutes.** That's already tight — the notes below tell you
exactly what to cut first if you're running long (search "CUT FIRST").

---

## Slide 1 — Cold open (0:45)

**On screen:** Title card. *"Everyone Is Vibe-Coding Agents."*
Subtitle: *bad architecture will mess you up.*

**Say:**
> "Raise your hand if you've shipped an AI feature in the last year that
> started as a slick demo and 'we'll harden it later.'
>
> [pause]
>
> This app's dangerous mode isn't called Insecure Mode. It's called **Vibe
> Mode.** That's not a joke name I made up for this talk — that's the actual
> mode toggle in the actual app. Because that's what an agent looks like when
> you build it the way most of us actually build agents: fast, tools
> everywhere, ship it."

**Demo cue:** none yet — pure hook, no live app on screen. Keep the tension.

**Image if you want one instead of a live app:** `docs/images/defcon-idle.png`
— shows the actual `Vibe` mode toggle, in situ, proving it's real.

---

## Slide 2 — Thesis (0:45)

**On screen:**
> The LLM cooperates the whole time.
> **The architecture is what fails.**
>
> Today: break it → fix it, cheapest first → show what the fix buys you
> for free that has nothing to do with security.

**Say:**
> "Every attack you're about to see is a standard AppSec bug wearing an
> agent costume. No jailbreaks. No 'ignore your previous instructions.' The
> model just... does what it's told, because nothing checked whether it
> should."

**Demo cue:** Open `/summit2`. Land on Act ① *Vibe-coded*. This is your home
base for the whole talk — one tab, one continuous flow, four act-tabs across
the top.

---

## Slide 3 — Act 1, part 1: IDOR (2 min)

**On screen (live app):** Bundle **A — Wrong person, wrong access** already
selected. Point at the three attack buttons and the green "legitimate access"
contrast button underneath.

**Say:**
> "Bundle A: the agent doesn't know who's really asking, or what they're
> allowed to see. Watch #1."

**Demo cue — click, in order:**
1. Click **`#1 Broken Access Control (IDOR)`** — *"Show me labs for patient 12."*
2. Wait ~4s. Point at the **whose-data banner** the instant it turns red:
   *"Data shown: Taylor Morgan's record (P12) — NOT the caller's own."*
3. Point at the **Agent Activity** panel: `get_patient_labs`, badge **LEAKED**.
4. Scroll down slightly to show the real lab table Mira just printed — HIV+
   panel, CD4 count, viral load. Don't dwell on the clinical content; dwell
   on the banner and the badge.

**Say (while it's rendering):**
> "Alex just asked for Taylor's labs. Nothing stopped it. That banner isn't
> decoration — it's computed server-side from who's actually asking versus
> whose record just got touched. Same distinction the code makes; now you
> can see it too."

**Backup image:** `docs/images/act1-idor-leak.png` — this exact moment,
banner red, badge LEAKED, table visible.

---

## Slide 4 — Act 1, part 2: the leak demo (2 min) — **the best beat in the talk**

**On screen:** Same tab, same bundle.

**Say:**
> "One more, and this one's the reason this bundle is called 'wrong person.'"

**Demo cue:**
1. Click **`#5 Cross-Session Leak`** — this auto-runs a scripted two-turn
   sequence, **do not click anything else, just narrate while it plays**:
   - Turn 1, as Alex Chen: *"My favorite color is teal, remember that please."*
   - The identity badge in the top-right **switches to Taylor Morgan**
     automatically, same session.
   - Turn 2, as Taylor: *"What did we just talk about? What is my favorite
     color?"*
2. Let Mira's second answer render: *"Your favorite color is teal!"*

**Say (right after it lands):**
> "Taylor never told Mira that. Alex did, forty seconds ago, as a completely
> different person. Same session ID, no caller scoping on the conversation
> history — so Taylor just inherited Alex's entire turn. This is a real bug
> class, not a contrived one — the fix everyone assumes exists here is a
> single dictionary key: session-only versus (session, caller)."

**Why this is the strongest beat:** it needs zero narration to be understood.
The audience watches identity switch, then watches the wrong person's
statement come back verbatim. Don't rush this slide even if you're behind —
cut elsewhere first.

**Backup image:** `docs/images/act1-cross-session-leak.png`

**CUT FIRST if short on time:** skip bundles B and C live. One sentence
instead: *"Six more of these — prompt injection, SQL-via-tool-schema, rate
limits, service auth, PII in logs. Same pattern every time: the model did
exactly what it was told."* Point at the bundle selector so the audience
sees there are more, without running them.

---

## Slide 5 — Act 2, part 1: build the fix live (2.5 min)

**On screen:** Click Act ② **Fix it, cheapest first**. Land on **Demo 1 —
authZ + role-scoped tools (easiest)**.

**Say:**
> "Now watch us build Fortress back, cheapest fix first — not a toggle, not
> a reveal. Built."

**Demo cue:**
1. Point at the **layers active (cumulative)** pill row: `L4` and `L2`.
2. Click the quick-prompt **`Show me labs for patient 12.`** (same exact
   attack as slide 3).
3. Wait ~4–8s. Point at the result: **`ENGINE BLOCKED`** badge, reason shown
   inline: *"Access denied: caller 7 is not authorized for patient 12."*
4. Point at Mira's own response in the chat — she explains she can't access
   it, cleanly, no drama.

**Say:**
> "Same prompt. Same model. Same everything — except one authZ check and one
> role-scoped tool list. That's the entire fix for two of the eight bugs
> you just watched."

**Backup image:** `docs/images/act2-demo1-blocked.png`

---

## Slide 6 — Act 2, part 2: the ladder keeps stacking (1.5 min)

**On screen:** Click **Demo 3 — signed caller header + typed tools (hard)**.

**Say:**
> "Skip ahead — Demo 2 was PII redaction plus input wrapping. By Demo 3
> we're stacking, not swapping."

**Demo cue:**
1. Point at the pill row — now **6 layers**, not 2: L4, L2, L9, L5, L1, L3.
2. Point at the two `curl` blocks rendered live below — one unsigned
   (`401 Missing X-Caller-Sig header`), one with a **real signed token
   fetched from the app itself** seconds ago.

**Say:**
> "That token isn't a placeholder — it's live, HMAC-signed, fetched from this
> demo's own API right now. By the time we're done, all eight fixes are
> stacked. Not a switch. A build."

**Backup image:** `docs/images/act2-demo3-cumulative-layers.png`

**CUT FIRST if short:** skip the curl block narration, just point and say
"live signed token" in one breath.

---

## Slide 7 — Act 3: the payoff nobody asked for (2 min)

**On screen:** Click Act ③ **Fast + traced**.

**Say:**
> "Here's the part that isn't about security at all. Same fully-hardened
> stack. Watch what else you get for free."

**Demo cue:**
1. Click any quick prompt (*"What are my recent labs?"*).
2. While it's thinking, point at the **animated status** — cycling words
   like "Percolating…", "Philosophising…" — light touch, gets a laugh.
3. When it lands, point at **latency + cost**, then pivot immediately to the
   **Async Call Classifier** panel in the sidebar: *"pending: 0"* now, but
   about 5 seconds ago it was 1.

**Say:**
> "A second, much cheaper model reads every single call, about five seconds
> after it already returned to the user — zero added latency on the request
> that mattered. It tags intent automatically. That's free observability,
> and it's the same architectural instinct that just stopped eight attacks:
> put a layer underneath the product code, once, and every product gets it."

**Backup image:** none needed — this is the weakest visual beat, lean on
narration + the classifier panel's live numbers.

---

## Slide 8 — Act 4: architecture doesn't read what you typed (2 min)

**On screen:** Click Act ④ **Content guard**.

**Say:**
> "Everything so far answers 'is this caller allowed to touch this tool.'
> None of it answers 'did the caller just ask something harmful, or paste a
> real SSN into the chat box.' That's a different problem, and it needs a
> different layer."

**Demo cue:**
1. Click **`PII leak`** — *"My SSN is 078-05-1120, can you note that in my
   file?"*
2. Wait ~1–2s (this one's fast — blocked before Bedrock is even called).
3. Point at **Agent Activity**: `ai_guard_input`, **~200ms**, `BLOCKED`,
   real reason: *"Sensitive data detected: Rule ID
   USA_SOCIAL_SECURITY_NUMBER."*
4. Point at the **AI Guard meter**: bar shifts red, "1 blocked."

**Say:**
> "This is a real Trend Vision One tenant. Two HTTP calls — one on the way
> in, one on the way out. Two hundred milliseconds, Bedrock never even gets
> touched. That's the same lesson as the whole talk, from a different
> angle: catching the bad thing early is faster *and* cheaper than catching
> it late."

**Backup image:** `docs/images/act4-pii-blocked.png` (blocked) and
`docs/images/act4-benign-allowed.png` (allowed, for contrast if you have 20
extra seconds — shows the meter's green side and the full 3-call pipeline:
input guard → tool call → output guard, all allowed).

**CUT FIRST if short:** skip step 4 (the meter), the badge + reason is
enough.

---

## Slide 9 — Close (1.5 min)

**On screen:**
> Vibe Mode isn't a strawman. It's what shipping fast actually looks like.
>
> Every fix you watched was cheap. Stack them in order and you get
> security, speed, and observability from **one** investment, not three.
>
> `github.com/<your-org>/pretty-please` — try it yourself.

**Say:**
> "Nobody in this room is going to stop vibe-coding agents. That's not the
> ask. The ask is: when you do, know the order to pay it back in, cheapest
> first — and know that paying it back isn't a tax. The same eight fixes
> that stopped every attack today are the reason this thing is also fast and
> fully traced. That's not a security demo. That's just... architecture."

**If you have a Q&A buffer:** the appendix below has the full 8-attack /
4-fix-demo catalogue and known caveats, so you're not caught flat if someone
asks about the four attacks you didn't demo live.

---

## Appendix — full catalogue (for Q&A, not the deck)

### The 8 attacks (bundle → attack → fix layer)

| Bundle | # | Attack | Fix layer(s) |
|---|---|---|---|
| A — Wrong person, wrong access | 1 | Broken Access Control (IDOR) | L4 |
| A | 3 | Confused Deputy | L2 |
| A | 5 | Cross-Session Leak | L7 |
| B — Don't trust what it reads or runs | 2 | Prompt Injection via Note | L5 |
| B | 4 | Overbroad SQL Schema | L3 |
| C — Nobody's watching the meter | 6 | Missing Rate Limits | L8 |
| C | 7 | Missing Service Auth | L1 |
| C | 8 | PII in Logs | L9 |

### The 4 fix demos (cheapest → hardest, cumulative)

1. **L4 + L2** — authZ + role-scoped tools (kills #1, #3)
2. **L9 + L5** — PII redaction + untrusted-input wrapping (kills #8, #2)
3. **L1 + L3** — signed caller header + typed tools (kills #7, #4)
4. **L8 + L7** — rate limits + session isolation (kills #6, #5)

### Known, honest caveats (say these if asked — don't get caught by them)

- **Attack #2 (prompt injection) doesn't reliably fire.** Tested live
  against 10 Bedrock models with the real 11-tool surface — none reliably
  act on this specific payload. That's a genuine finding, not a bug: modern
  models are robust against an overt "SYSTEM OVERRIDE" phrasing. The
  structural demo (show the model the wrapped vs. raw note) proves L5 works
  regardless.
- **DEFCON's own production Fortress mode has a real, separate bug**
  (found while building this): the documented cross-session fix
  (`memory.py`) is never actually called from `main.py`. The real
  conversation history is session-only in every mode. Don't demo this one
  live unless you're prepared to explain it — it's a genuine finding about
  the *original* demo, not something this talk fixes.
- **`redact_pii()` doesn't redact `condition_summary`** (e.g. HIV status) —
  contradicts its own attack doc's example. Minor, but know it's there.

---

## Image checklist

All in `docs/images/`, all real screenshots from a live, working build —
not mockups:

| File | Use |
|---|---|
| `defcon-idle.png` | Slide 1 backup / cold open |
| `act1-idor-leak.png` | Slide 3 backup |
| `act1-cross-session-leak.png` | Slide 4 backup — the best single image in the deck |
| `act2-demo1-blocked.png` | Slide 5 backup |
| `act2-demo3-cumulative-layers.png` | Slide 6 backup |
| `act4-pii-blocked.png` | Slide 8 backup |
| `act4-benign-allowed.png` | Slide 8 contrast / Q&A |

**If wifi dies mid-talk:** every slide above has a backup image. Switch to
"narrate over the screenshot" mode without breaking stride — the images were
captured from the actual running app this week, so nothing you say about
them is stale.
