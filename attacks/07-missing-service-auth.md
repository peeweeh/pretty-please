# Attack 7 — Missing Service Auth on MCP Endpoints

**Class:** Missing authentication on internal service endpoints  
**Guardrail fix:** L1 — HMAC-signed `X-Caller-Sig` header; `verify_caller()` on every fortress endpoint

## What happens

The Vibe mode MCP-style HTTP endpoints at `/mcp-vibe/{tool_name}` have no authentication. Anyone on the network can call tools directly — bypassing the LLM entirely. This demonstrates that the LLM is just a middleman: the vulnerability is in the tool layer.

## The LLM is irrelevant for this attack

```bash
# No LLM. No session. No login. Just curl.
curl -X POST localhost:9000/mcp-vibe/get_patient_labs \
  -H "Content-Type: application/json" \
  -d '{"patient_id": 12}'
```

Returns Taylor Morgan's HIV+ labs immediately.

## Live demo

This attack opens a modal with the curl commands side-by-side. Run from your own terminal during the talk.

## Expected outcomes

| Endpoint | Result |
|---|---|
| `POST /mcp-vibe/get_patient_labs` | 200 OK — full lab data |
| `POST /mcp-fortress/get_patient_labs` | 401 — Missing X-Caller-Sig header |

## How Fortress blocks it

```python
@app.post("/mcp-fortress/{tool_name}")
async def mcp_fortress(tool_name: str, req: ToolCallRequest,
                        x_caller_sig: str = Header(None)):
    if not x_caller_sig:
        raise HTTPException(status_code=401, detail="Missing X-Caller-Sig header")
    caller_id = verify_caller(x_caller_sig, session_id="mcp-demo")
    ...
```

The HMAC token is issued server-side at session start and bound to `(caller_id, session_id, timestamp)`. The LLM never sees it.

## Why this matters

MCP (Model Context Protocol) is gaining adoption. If tool servers are exposed on the network without auth, they become directly exploitable — no prompt engineering required. This is a standard API security failure in new clothing.
