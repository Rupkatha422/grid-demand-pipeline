"""Minimal Groq client (OpenAI-compatible REST API) used by the AI briefing and the dashboard assistant.

Kept dependency-free (just requests) so it runs in both the Airflow image and Streamlit.
"""
import json
import os
from pathlib import Path

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"


def _read_env_file(name: str) -> str:
    """Fallback for local runs outside Docker: read a value from the repo's .env file."""
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    return ""


def api_key() -> str:
    return os.getenv("GROQ_API_KEY") or _read_env_file("GROQ_API_KEY")


def model() -> str:
    return os.getenv("GROQ_MODEL") or _read_env_file("GROQ_MODEL") or DEFAULT_MODEL


def chat(messages: list[dict], *, json_mode: bool = False, temperature: float = 0.2,
         max_tokens: int = 800, key: str | None = None) -> str:
    """Send a chat completion request and return the assistant's text (or JSON string)."""
    key = key or api_key()
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to .env.")
    body = {"model": model(), "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if "gpt-oss" in body["model"]:
        # Reasoning model: keep thinking short so the answer fits in max_tokens.
        body["reasoning_effort"] = "low"
        body["max_tokens"] = max_tokens + 1000
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    resp = requests.post(GROQ_URL, json=body, timeout=60,
                         headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    if resp.status_code >= 400:
        raise RuntimeError(f"Groq API error {resp.status_code}: {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]["content"]


def chat_json(messages: list[dict], **kwargs) -> dict:
    return json.loads(chat(messages, json_mode=True, **kwargs))
