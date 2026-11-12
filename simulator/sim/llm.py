"""A minimal client for an OpenAI-compatible chat server (vLLM in the study), standard library only."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class Reply:
    text: str
    tokens_in: int
    tokens_out: int
    seconds: float
    finish_reason: str


class Client:
    def __init__(self, base_url: str, model: str = "local", timeout: float = 600, retries: int = 6,
                 thinking_switch: bool = True):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.thinking_switch = thinking_switch   # send chat_template_kwargs.enable_thinking (Qwen templates)

    def _post(self, path: str, body: dict) -> dict:
        request = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:500]
                if error.code < 500 or attempt == self.retries - 1:
                    raise RuntimeError(f"HTTP {error.code} from {path}: {detail}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                if attempt == self.retries - 1:
                    raise
            time.sleep(min(60, 2 ** attempt))
        raise RuntimeError("unreachable")

    def chat(self, messages: list, *, temperature: float, max_tokens: int, top_p: float | None = None,
             top_k: int | None = None, seed: int | None = None, schema: dict | None = None,
             schema_name: str = "output", thinking: bool = False) -> Reply:
        body = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if top_p is not None:
            body["top_p"] = top_p
        if top_k is not None:
            body["top_k"] = top_k
        if seed is not None:
            body["seed"] = seed
        if schema is not None:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": schema_name, "schema": schema, "strict": True}}
        if self.thinking_switch:
            body["chat_template_kwargs"] = {"enable_thinking": thinking}
        start = time.time()
        data = self._post("/chat/completions", body)
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        return Reply(text=choice["message"].get("content") or "", tokens_in=usage.get("prompt_tokens", 0),
                     tokens_out=usage.get("completion_tokens", 0), seconds=time.time() - start,
                     finish_reason=choice.get("finish_reason") or "")

    def models(self) -> dict:
        with urllib.request.urlopen(self.base_url + "/models", timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))


def parse_json(text: str) -> dict:
    """The JSON object in a model's output (tolerates code fences and text around it)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the output")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("the output is not a JSON object")
    return value
