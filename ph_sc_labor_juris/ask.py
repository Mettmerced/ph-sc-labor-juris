"""Ask a question against the retrieved labor decisions."""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.request

from ph_sc_labor_juris.index import search


def _context(rows: list[sqlite3.Row]) -> str:
    blocks = []
    for index, row in enumerate(rows, start=1):
        blocks.append(
            f"[{index}] {row['docket']} ({row['decided_on']})\n"
            f"Title: {row['title']}\n"
            f"Source: {row['url']}\n"
            f"{row['text']}"
        )
    return "\n\n".join(blocks)


def generate_answer(question: str, rows: list[sqlite3.Row]) -> str | None:
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if groq_key:
        url = "https://api.groq.com/openai/v1/chat/completions"
        key = groq_key
        model = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
    elif openai_key:
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        url = f"{base}/chat/completions"
        key = openai_key
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    else:
        return None

    prompt = (
        "You answer questions about Philippine labor law using only the Supreme Court "
        "passages below. Cite the G.R. number and date for each point you use. "
        "If the passages do not answer the question, say that you did not find it "
        "in the retrieved decisions. Do not add doctrine from memory.\n\n"
        f"Question: {question}\n\nPassages:\n{_context(rows)}"
    )
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": "You are a careful legal research assistant."},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"].strip()


def format_passages(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return "No matching labor decisions are in the local index yet."
    parts = []
    for index, row in enumerate(rows, start=1):
        excerpt = row["text"].strip()
        if len(excerpt) > 900:
            excerpt = excerpt[:900].rstrip() + "..."
        parts.append(
            f"[{index}] {row['docket']} ({row['decided_on']})\n"
            f"{row['title']}\n"
            f"{row['url']}\n\n"
            f"{excerpt}"
        )
    return "\n\n".join(parts)
