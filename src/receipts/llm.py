"""Nebius Token Factory client (OpenAI-compatible) + an offline mock.

Everything in this repo must be runnable **without** a key (that is how the tests run), and
must be honest about what it is talking to. So: one small wrapper, one explicit mock, and a
``smoke()`` that proves a real key works end to end.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

DEFAULT_BASE_URL = "https://api.tokenfactory.us-central1.nebius.com/v1/"
DEFAULT_ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"
DEFAULT_FAST = "nvidia/Nemotron-3_5-Lightning"


def _env(name: str, default: str) -> str:
    val = os.environ.get(name, "").strip()
    return val or default


def load_dotenv(path: str | os.PathLike | None = None) -> dict[str, str]:
    """Read a .env file into os.environ (never overwriting what is already set).

    Hand-rolled on purpose: one less dependency, and the behaviour is obvious to a reader.
    Returns the keys it actually set, so a caller can report them without printing values.
    """
    candidates = [Path(path)] if path else []
    candidates += [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]
    applied: dict[str, str] = {}
    for candidate in candidates:
        try:
            raw = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                applied[key] = value
        break
    return applied


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict = field(default_factory=dict)
    raw: Any = None


class NebiusClient:
    """Thin wrapper. Base URL and model ids come from the environment (see .env.example)."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        load_dotenv()
        self.api_key = api_key or os.environ.get("NEBIUS_API_KEY", "").strip()
        self.base_url = base_url or _env("RECEIPTS_BASE_URL", DEFAULT_BASE_URL)
        self.model_ultra = _env("RECEIPTS_MODEL_ULTRA", DEFAULT_ULTRA)
        self.model_fast = _env("RECEIPTS_MODEL_FAST", DEFAULT_FAST)
        self._client = None

    # -- plumbing ------------------------------------------------------------------------

    @property
    def client(self):
        if self._client is None:
            if not self.api_key:
                raise RuntimeError(
                    "NEBIUS_API_KEY is not set. Copy .env.example to .env and add your key "
                    "(get one at https://tokenfactory.nebius.com/)."
                )
            from openai import OpenAI  # imported lazily so the repo works offline

            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        return self._client

    def models(self) -> list[str]:
        return [m.id for m in self.client.models.list().data]

    def chat(
        self,
        messages: Sequence[dict],
        tools: Sequence[dict] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> Reply:
        kwargs: dict[str, Any] = {
            "model": model or self.model_ultra,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = list(tools)
            kwargs["tool_choice"] = "auto"
        resp = self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0].message
        calls = []
        for tc in (choice.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        usage = {}
        if getattr(resp, "usage", None):
            usage = resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else dict(resp.usage)
        return Reply(text=choice.content or "", tool_calls=calls,
                     model=getattr(resp, "model", ""), usage=usage, raw=resp)


class MockClient:
    """Offline stand-in with the same surface. Scripted replies, no network, no key."""

    def __init__(self, script: Iterable[Reply | str] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[dict] = []
        self.model_ultra = "mock-ultra"
        self.model_fast = "mock-fast"

    def chat(self, messages, tools=None, model=None, temperature=0.2, max_tokens=2048) -> Reply:
        self.calls.append({"messages": list(messages), "tools": list(tools or []), "model": model})
        if not self.script:
            return Reply(text="(mock) nothing scripted", model=model or self.model_ultra)
        item = self.script.pop(0)
        return item if isinstance(item, Reply) else Reply(text=item, model=model or self.model_ultra)

    def models(self) -> list[str]:
        return ["mock-ultra", "mock-fast"]


def smoke(client: NebiusClient | None = None, model: str | None = None) -> dict:
    """One real call. This is the artifact that says 'the key works'."""
    c = client or NebiusClient()
    reply = c.chat(
        [{"role": "user", "content": "Reply with exactly the word: ready"}],
        model=model,
        max_tokens=16,
        temperature=0.0,
    )
    return {
        "base_url": c.base_url,
        "model": reply.model or model or c.model_ultra,
        "text": reply.text.strip(),
        "usage": reply.usage,
    }


if __name__ == "__main__":  # python -m receipts.llm
    import sys

    try:
        print(json.dumps(smoke(), indent=2, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - the point is to print why it failed
        print(f"smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
