"""Model clients for Gate 3.

Every call sends one system prompt and one user message and nothing else, so
each call starts from a fresh context. Any object with a
complete(system, user) -> str method can stand in for a client; the tests use
a fake one.
"""

import json
import os
import re

import requests


class ModelError(Exception):
    """The model call failed or returned output we could not parse (Tool fault)."""

    def __init__(self, message, raw=""):
        super().__init__(message)
        self.raw = raw


class CountingClient:
    """Wraps a client and counts calls, for the model-calls-per-record proxy."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self.inner.complete(system, user)


class OpenAIChatClient:
    """OpenAI-compatible chat completions client, matching annotation_daemon.py.

    Reads OPENAI_API_KEY and OPENAI_API_URL from the environment (or the
    .env file passed as env_file) unless they are given directly.
    """

    def __init__(self, model, temperature=0.0, api_key=None, api_url=None, env_file=None, timeout=120):
        config = {}
        if env_file:
            from dotenv import dotenv_values
            config = dotenv_values(env_file)
        self.api_key = api_key or config.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.api_url = (api_url or config.get("OPENAI_API_URL") or os.environ.get("OPENAI_API_URL")
                        or "https://api.openai.com/v1/chat/completions")
        if not self.api_key:
            raise ModelError("OPENAI_API_KEY is not set")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Content-Type": "application/json", "Authorization": "Bearer %s" % self.api_key}
        resp = requests.post(self.api_url, json=body, headers=headers, timeout=self.timeout)
        if resp.status_code != 200:
            raise ModelError("HTTP %d from model API" % resp.status_code, resp.text)
        return resp.json()["choices"][0]["message"]["content"]


def parse_json_reply(raw: str):
    """Parse a JSON reply, tolerating a ```json fence around it."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ModelError("model reply is not valid JSON: %s" % e, raw)
