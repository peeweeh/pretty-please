# pretty-please

> "bad architecture choices will mess you up" — DEFCON 2026 / AWS Summit demo

A live agent security demo showing that **architecture failures — not LLM jailbreaks — leak patient data**.

Same LLM. Same prompts. Same 8 attacks. Two modes: **Vibe** (dangerous) and **Fortress** (safe).

---

## 60-second run

```bash
cp .env.example .env
# set AWS_REGION=us-east-1 in .env (Bedrock via EC2 instance role)
docker compose up
open http://localhost:8000
```

Then pick an attack from the dropdown and toggle between Vibe and Fortress modes.

---

## The thesis

The LLM cooperates the whole time. The architecture is what fails.

Every attack class is a standard AppSec bug dressed in agent clothing:
- Broken access control (IDOR)
- Prompt injection via data
- Confused deputy / tool loading
- SQL injection via overbroad tool schema
- Cross-session context leak
- Missing rate limits
- Missing service auth on MCP endpoints
- PII in logs

---

## 8 attacks

See `attacks/` for exec-ready stage scripts.

---

## Tech

- **Single Python container** — FastAPI + uvicorn
- **SQLite** — `medimind.db`, reseeded every 5 minutes
- **Vanilla HTML + Alpine.js + HTMX** — zero Node build step
- **3 translators** — Plain Bedrock / Strands Agents / Ollama (offline)
- **AWS Bedrock Haiku 4.5** — via EC2 instance role (no `AWS_PROFILE`)

---

## Offline mode (conference wifi fallback)

```bash
docker compose --profile offline up
# pulls qwen2.5:7b on first run
```

---

## ⚠️ This is demo software

Synthetic data. Fake patients. DO NOT connect to real infrastructure.
