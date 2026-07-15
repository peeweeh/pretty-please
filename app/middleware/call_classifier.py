"""
call_classifier.py — Summit 2.0 Act 3 headline (PP-07g): async, non-blocking
call tagging.

Every chat call is logged to ai_calls_log immediately (fire-and-forget —
never blocks the user-facing response). A background task polls every 5s,
batches unclassified rows, tags them with a cheap Bedrock model (Amazon
Nova Micro — deliberately not the main chat model, for the cost contrast),
and writes ai_calls_classified.
"""

import asyncio
import logging
import os
import time
import uuid

import boto3

from ..db import conn

logger = logging.getLogger("uvicorn.error")

CLASSIFIER_MODEL_ID = os.environ.get("SUMMIT2_CLASSIFIER_MODEL_ID", "us.amazon.nova-micro-v1:0")
POLL_INTERVAL_SECONDS = 5
BATCH_LIMIT = 20
INTENT_VALUES = [
    "Labs Lookup",
    "Clinical Notes",
    "Medication Question",
    "Appointment",
    "Account / Security",
    "Personal Info Recall",
    "Escalation / Safety Concern",
    "Other",
]

# One line of context per intent, shown to the classifier model — a plain
# label list left Nova Micro guessing on anything outside "obvious" patient
# support requests (chart notes, admin/SQL-style asks, memory-recall demo
# prompts), so most of this app's actual traffic fell into "Other".
_CLASSIFIER_SYSTEM_PROMPT = (
    "You are tagging messages sent to MediMind Health, a patient-support chatbot used in a "
    "security demo (so some messages are deliberately adversarial test prompts, not real patient "
    "requests). Classify the user's message into exactly ONE of these intents:\n"
    "- Labs Lookup: asking to see lab/test results, for themselves or another patient.\n"
    "- Clinical Notes: asking to see, summarize, or discuss doctor's notes or chart entries.\n"
    "- Medication Question: asking about a prescription, dosage, refill, or side effect.\n"
    "- Appointment: asking about scheduling or upcoming visits.\n"
    "- Account / Security: password/credential resets, admin tool use, raw database/SQL "
    "requests, or anything trying to reach system internals rather than clinical data.\n"
    "- Personal Info Recall: asking the assistant to remember, recall, or repeat back a "
    "personal fact (name, favorite thing, hometown, prior conversation, etc.).\n"
    "- Escalation / Safety Concern: harmful, dangerous, or self-harm/violence-adjacent requests.\n"
    "- Other: only if it genuinely fits nothing above.\n"
    "Reply with only the label, nothing else."
)
# Demo-only approximation of Nova Micro on-demand pricing (per token, USD).
_NOVA_MICRO_IN = 0.035e-6
_NOVA_MICRO_OUT = 0.14e-6

_bedrock = None


def _client():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _bedrock


def log_call(*, product: str, caller_id: int, prompt: str, model_id: str, latency_ms: float, cost_usd: float) -> str:
    """Fire-and-forget write — called right after a chat response returns, never blocks it."""
    call_id = str(uuid.uuid4())
    with conn() as c:
        c.execute(
            "INSERT INTO ai_calls_log "
            "(call_id, product, caller_id, prompt, model_id, latency_ms, cost_usd, classified) "
            "VALUES (?,?,?,?,?,?,?,0)",
            (call_id, product, caller_id, prompt[:500], model_id, latency_ms, cost_usd),
        )
        c.commit()
    return call_id


def _classify_one(row: dict) -> None:
    tag = "Other"
    cost = 0.0
    try:
        start = time.perf_counter()
        resp = _client().converse(
            modelId=CLASSIFIER_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": row["prompt"]}]}],
            system=[{"text": _CLASSIFIER_SYSTEM_PROMPT}],
            inferenceConfig={"maxTokens": 20},
        )
        text = resp["output"]["message"]["content"][0]["text"].strip()
        tag = text if text in INTENT_VALUES else "Other"
        usage = resp.get("usage", {})
        cost = usage.get("inputTokens", 0) * _NOVA_MICRO_IN + usage.get("outputTokens", 0) * _NOVA_MICRO_OUT
    except Exception as e:
        logger.warning(f"[CLASSIFIER] failed call_id={row['call_id']}: {e}")
    with conn() as c:
        c.execute(
            "INSERT INTO ai_calls_classified (call_id, intent, classifier_model, classifier_cost_usd) "
            "VALUES (?,?,?,?)",
            (row["call_id"], tag, CLASSIFIER_MODEL_ID, cost),
        )
        c.execute("UPDATE ai_calls_log SET classified=1 WHERE call_id=?", (row["call_id"],))
        c.commit()


def _classify_batch(rows: list[dict]) -> None:
    for row in rows:
        _classify_one(row)


async def poll_loop():
    """Runs forever as a background asyncio task, started once at app startup."""
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        with conn() as c:
            rows = [
                dict(r)
                for r in c.execute(
                    "SELECT call_id, prompt FROM ai_calls_log WHERE classified=0 "
                    "ORDER BY created_at LIMIT ?",
                    (BATCH_LIMIT,),
                ).fetchall()
            ]
        if rows:
            await asyncio.to_thread(_classify_batch, rows)


def status() -> dict:
    with conn() as c:
        pending = c.execute("SELECT COUNT(*) n FROM ai_calls_log WHERE classified=0").fetchone()["n"]
        recent = c.execute(
            "SELECT l.call_id, l.product, l.caller_id, l.prompt, cl.intent, "
            "cl.classifier_cost_usd, cl.classified_at "
            "FROM ai_calls_classified cl JOIN ai_calls_log l ON l.call_id = cl.call_id "
            "ORDER BY cl.classified_at DESC LIMIT 5"
        ).fetchall()
        total_cost = c.execute(
            "SELECT COALESCE(SUM(classifier_cost_usd), 0) s FROM ai_calls_classified"
        ).fetchone()["s"]
    return {
        "pending": pending,
        "recent": [dict(r) for r in recent],
        "total_classifier_cost_usd": round(total_cost, 6),
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "classifier_model": CLASSIFIER_MODEL_ID,
    }
