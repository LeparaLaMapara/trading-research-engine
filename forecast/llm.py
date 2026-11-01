"""One doorway to a language model, so the news reader never cares which model answers.

Switch with ONE setting, no code change:

    NEWS_LLM=local     -> a model on this PC through Ollama (free; default)
    NEWS_LLM=api       -> Claude through the Anthropic API (needs ANTHROPIC_API_KEY in .env)
    NEWS_LLM=ollama:<model>  or  anthropic:<model>  -> any specific model

What the doorway adds, whichever model is behind it:

* **Record and replay.** Every answer is kept in data/forecast/llm-replay.jsonl, keyed on the
  backend, model, system text, prompt and limits. Asking the same thing again returns the kept
  answer, so re-testing the reader on past news costs nothing and gives the same answers.
  NEWS_LLM_MODE=live (always ask), record (default: reuse, else ask and keep), replay (kept
  answers only; a miss is an error, never a silent call).
* **A budget guard.** Before any paid call it estimates the cost and refuses if this calendar
  month's spend plus the estimate would pass NEWS_LLM_MONTHLY_USD (default $5). Local models
  cost $0. Every call is logged to data/forecast/llm-usage.jsonl.
* **Checked answers.** complete_json() parses the answer and asks again, a set number of times,
  only when it is not valid JSON with the expected keys.

The shape (port, complete, an answer with text, tokens, model and request_key) follows the
Ubunye Engine's LLM port, so Ubunye can sit behind this doorway later without the reader
changing.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass

from config import settings  # noqa: F401  (loads .env so the API key is in the environment)

REPLAY = "data/forecast/llm-replay.jsonl"
USAGE = "data/forecast/llm-usage.jsonl"
PROFILES = {"local": "ollama:qwen3.5:9b", "api": "anthropic:claude-haiku-5-5"}
#: US dollars per million tokens (input, output), Anthropic first-party prices, 2026-10.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00),
          "claude-opus-5-5": (4.00, 20.00)}
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


class LLMBudgetError(RuntimeError):
    pass


class LLMReplayMiss(RuntimeError):
    pass


@dataclass
class Answer:
    text: str
    model: str
    backend: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    request_key: str = ""
    replayed: bool = False


# -- backends: each turns (system, prompt, max_tokens) into an Answer, nothing more -------------
class OllamaBackend:
    name = "ollama"

    def __init__(self, model: str) -> None:
        self.model = model

    def price(self) -> tuple[float, float]:
        return 0.0, 0.0

    def ask(self, prompt: str, system: str | None, max_tokens: int) -> Answer:
        import requests
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        r = requests.post(f"{OLLAMA_URL}/api/chat", timeout=300, json={
            "model": self.model, "messages": msgs, "stream": False, "think": False,
            "options": {"temperature": 0, "num_predict": max_tokens}})
        r.raise_for_status()
        d = r.json()
        return Answer(text=d.get("message", {}).get("content", ""), model=self.model, backend=self.name,
                      input_tokens=int(d.get("prompt_eval_count") or 0),
                      output_tokens=int(d.get("eval_count") or 0))


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, model: str) -> None:
        self.model = model
        self._client = None

    def price(self) -> tuple[float, float]:
        if self.model not in PRICES:
            raise LLMBudgetError(f"no price known for {self.model}: add it to PRICES before paying for it")
        return PRICES[self.model]

    def ask(self, prompt: str, system: str | None, max_tokens: int) -> Answer:
        import anthropic
        if self._client is None:
            self._client = anthropic.Anthropic()
        kw = {"system": system} if system else {}
        resp = self._client.messages.create(
            model=self.model, max_tokens=max_tokens, output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}], **kw)
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"{self.model} declined the request")
        text = "".join(b.text for b in resp.content if b.type == "text")
        pin, pout = self.price()
        cost = (resp.usage.input_tokens * pin + resp.usage.output_tokens * pout) / 1e6
        return Answer(text=text, model=self.model, backend=self.name, input_tokens=resp.usage.input_tokens,
                      output_tokens=resp.usage.output_tokens, cost_usd=cost)


BACKENDS = {"ollama": OllamaBackend, "anthropic": AnthropicBackend}


# -- the doorway ---------------------------------------------------------------------------------
def _jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]


def _append(path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


class Port:
    def __init__(self, backend, mode: str = "record", monthly_usd: float = 5.0,
                 replay_path: str | None = None, usage_path: str | None = None) -> None:
        self.backend = backend
        self.mode = mode
        self.monthly_usd = monthly_usd
        self.replay_path = replay_path or REPLAY
        self.usage_path = usage_path or USAGE

    @property
    def spec(self) -> str:
        return f"{self.backend.name}:{self.backend.model}"

    def key(self, prompt: str, system: str | None, max_tokens: int) -> str:
        body = json.dumps({"spec": self.spec, "system": system or "", "prompt": prompt,
                           "max_tokens": max_tokens}, sort_keys=True)
        return hashlib.sha256(body.encode()).hexdigest()

    def spent_this_month(self) -> float:
        month = time.strftime("%Y-%m", time.gmtime())
        return sum(r.get("cost_usd", 0.0) for r in _jsonl(self.usage_path) if r.get("month") == month)

    def complete(self, prompt: str, system: str | None = None, max_tokens: int = 512) -> Answer:
        k = self.key(prompt, system, max_tokens)
        if self.mode in ("record", "replay"):
            for r in reversed(_jsonl(self.replay_path)):
                if r["request_key"] == k:
                    return Answer(**{**r["answer"], "replayed": True, "cost_usd": 0.0})
            if self.mode == "replay":
                raise LLMReplayMiss(f"no kept answer for this request ({self.spec}); run in record mode once")
        pin, pout = self.backend.price()
        estimate = (len((system or "") + prompt) / 3 * pin + max_tokens * pout) / 1e6
        if estimate > 0 and self.spent_this_month() + estimate > self.monthly_usd:
            raise LLMBudgetError(f"refused before calling {self.spec}: this month's spend "
                                 f"${self.spent_this_month():.4f} + about ${estimate:.4f} would pass "
                                 f"the ${self.monthly_usd:.2f} limit (NEWS_LLM_MONTHLY_USD)")
        t0 = time.time()
        a = self.backend.ask(prompt, system, max_tokens)
        a.request_key = k
        _append(self.usage_path, {"month": time.strftime("%Y-%m", time.gmtime()), "ts": time.time(),
                                  "spec": self.spec, "input_tokens": a.input_tokens,
                                  "output_tokens": a.output_tokens, "cost_usd": a.cost_usd,
                                  "seconds": round(time.time() - t0, 2)})
        if self.mode == "record":
            _append(self.replay_path, {"request_key": k, "spec": self.spec, "answer": asdict(a)})
        return a

    def complete_json(self, prompt: str, keys: tuple[str, ...], system: str | None = None,
                      max_tokens: int = 512, retries: int = 2) -> tuple[dict | None, list[Answer]]:
        """Ask for JSON with `keys`; ask again (only on a bad answer) up to `retries` times.
        Returns (parsed or None, every answer received)."""
        answers, ask = [], prompt
        for attempt in range(retries + 1):
            a = self.complete(ask, system, max_tokens)
            answers.append(a)
            parsed = parse_json(a.text, keys)
            if parsed is not None:
                return parsed, answers
            ask = prompt + f"\n\nReply with ONLY a JSON object with the keys {list(keys)}. Attempt {attempt + 2}."
        return None, answers


def parse_json(text: str, keys: tuple[str, ...]) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) and all(k in d for k in keys) else None


def port(spec: str | None = None, mode: str | None = None, monthly_usd: float | None = None, **kw) -> Port:
    """port() reads NEWS_LLM ("local", "api", or "backend:model"); nothing else changes on a switch."""
    spec = spec or os.environ.get("NEWS_LLM", "local")
    spec = PROFILES.get(spec, spec)
    name, _, model = spec.partition(":")
    if name not in BACKENDS or not model:
        raise ValueError(f"unknown model setting {spec!r}: use local, api, ollama:<model> or anthropic:<model>")
    return Port(BACKENDS[name](model),
                mode=mode or os.environ.get("NEWS_LLM_MODE", "record"),
                monthly_usd=monthly_usd if monthly_usd is not None else float(os.environ.get("NEWS_LLM_MONTHLY_USD", "5")),
                **kw)
