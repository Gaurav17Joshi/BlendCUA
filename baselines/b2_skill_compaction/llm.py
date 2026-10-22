"""OpenAI Responses API calls for B2: retries, usage accounting, image encoding.

Every call runs with the main system's executor model and reasoning effort
(b2_config.MODEL / REASONING_EFFORT) and store=False; reasoning is carried
between turns as encrypted content, so the client holds the whole conversation.
"""
from __future__ import annotations

import base64
import io
import time
from pathlib import Path

import b2_config as CFG

_client = None
_image_client = None


def client():
    """The agent's model. OpenAI directly, or OpenRouter, which serves the same
    (stateless) Responses API — see b2_config.PROFILES."""
    global _client
    if _client is None:
        CFG.load_keys()
        import os
        from openai import OpenAI
        kw = {"timeout": 1800, "max_retries": 0}
        if CFG.PROFILE["base_url"]:
            kw["base_url"] = CFG.PROFILE["base_url"]
            kw["api_key"] = os.environ[CFG.PROFILE["key_env"]]
        _client = OpenAI(**kw)
    return _client


def image_client():
    """Always OpenAI: gpt-image-2 is only served there, whatever model the agent runs on."""
    global _image_client
    if _image_client is None:
        if not CFG.PROFILE["base_url"]:
            return client()
        CFG.load_keys()
        import os
        from openai import OpenAI
        _image_client = OpenAI(timeout=1800, max_retries=0, api_key=os.environ["OPENAI_API_KEY"])
    return _image_client


class Usage:
    """Token and dollar totals over any number of calls."""

    def __init__(self):
        self.calls = 0
        self.input = 0          # all input tokens, cached included
        self.cached = 0
        self.cache_write = 0    # input tokens written to the prompt cache (gpt-6 reports them)
        self.output = 0         # reasoning included
        self.reasoning = 0
        self.peak_input = 0
        self.api_seconds = 0.0

    def add(self, usage, seconds: float = 0.0) -> float:
        """Fold in one response.usage; returns that call's cost."""
        self.calls += 1
        self.api_seconds += seconds
        if usage is None:
            return 0.0
        inp = int(getattr(usage, "input_tokens", 0) or 0)
        det = getattr(usage, "input_tokens_details", None)
        cached = int(getattr(det, "cached_tokens", 0) or 0) if det else 0
        written = int(getattr(det, "cache_write_tokens", 0) or 0) if det else 0
        out = int(getattr(usage, "output_tokens", 0) or 0)
        odet = getattr(usage, "output_tokens_details", None)
        reas = int(getattr(odet, "reasoning_tokens", 0) or 0) if odet else 0
        self.input += inp
        self.cached += cached
        self.cache_write += written
        self.output += out
        self.reasoning += reas
        self.peak_input = max(self.peak_input, inp)
        return CFG.cost_usd(inp - cached, cached, out, written)

    @property
    def cost(self) -> float:
        return CFG.cost_usd(self.input - self.cached, self.cached, self.output, self.cache_write)

    def as_dict(self) -> dict:
        return {"api_calls": self.calls, "input_tokens": self.input,
                "cached_input_tokens": self.cached, "cache_write_tokens": self.cache_write,
                "output_tokens": self.output,
                "reasoning_tokens": self.reasoning, "peak_input_tokens": self.peak_input,
                "api_seconds": round(self.api_seconds, 1), "cost_usd": round(self.cost, 4)}


RETRYABLE = ("RateLimitError", "APIConnectionError", "APITimeoutError",
             "InternalServerError", "ServiceUnavailableError", "APIStatusError")


def create(*, log=print, attempts: int = 10, **kwargs):
    """responses.create with the B2 defaults and backoff on transient errors."""
    kwargs.setdefault("model", CFG.MODEL)
    if CFG.PROFILE["openai_native"]:
        kwargs.setdefault("reasoning", {"effort": CFG.REASONING_EFFORT, "summary": "auto"})
        kwargs.setdefault("store", False)
        # Reasoning is carried between turns as encrypted content, so the client
        # holds the whole conversation. OpenRouter is stateless and serves no
        # encrypted reasoning, so both of these are OpenAI-only.
        kwargs.setdefault("include", ["reasoning.encrypted_content"])
    else:
        kwargs.setdefault("reasoning", {"effort": CFG.REASONING_EFFORT})
    delay = 10.0
    for i in range(attempts):
        t0 = time.time()
        try:
            r = client().responses.create(**kwargs)
            return r, time.time() - t0
        except Exception as e:  # noqa: BLE001
            name = type(e).__name__
            status = getattr(e, "status_code", None)
            if name == "BadRequestError" or (status is not None and 400 <= status < 500 and status != 429):
                raise
            if i == attempts - 1 or not any(n in name for n in RETRYABLE + ("Timeout",)):
                raise
            log(f"[llm] {name} ({str(e)[:200]}); retry {i + 1}/{attempts - 1} in {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 2, 300)


def image_part(path: Path | str, max_side: int = 1536, detail: str = "high") -> dict:
    """An input_image content part, downscaled so the long side is <= max_side."""
    from PIL import Image
    im = Image.open(path)
    im.load()
    if max(im.size) > max_side:
        s = max_side / max(im.size)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    buf = io.BytesIO()
    if im.mode in ("RGBA", "LA", "P"):
        im.convert("RGBA").save(buf, format="PNG")
        mime = "image/png"
    else:
        im.convert("RGB").save(buf, format="JPEG", quality=90)
        mime = "image/jpeg"
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"type": "input_image", "image_url": f"data:{mime};base64,{b64}", "detail": detail}
