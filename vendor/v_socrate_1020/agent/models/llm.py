import os
import base64
import io
import copy
import threading
import time
from typing import Any, Dict, List, Optional, Union

import httpx
from openai import OpenAI
from PIL import Image


def _extra_body() -> dict:
    """OpenAI-compatible extras for vLLM: shared sampling params (LLM_TOP_K,
    LLM_PRESENCE_PENALTY from configs/common_env.sh) and the chat-template switch."""
    body = {"top_k": int(os.environ["LLM_TOP_K"]),
            "presence_penalty": float(os.environ["LLM_PRESENCE_PENALTY"])}
    if os.environ["TAKA_DISABLE_THINKING"].strip().lower() in ("1", "true", "yes", "on"):
        body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


def _sampling_kwargs(config: Dict) -> dict:
    """Optional sampling params; only sent when configured (top_p=None -> server default)."""
    top_p = config.get("top_p")
    return {"top_p": float(top_p)} if top_p is not None else {}


def _split_base_urls(base_url: Union[str, List[str]]) -> List[str]:
    """Accept a single URL, a comma-separated string, or a list -> clean list."""
    if isinstance(base_url, (list, tuple)):
        items = list(base_url)
    else:
        items = str(base_url).split(",")
    out = [u.strip().rstrip("/") for u in items if u and u.strip()]
    return out or [""]


def check_endpoints(base_url: Union[str, List[str]], api_key: str, model: str, tag: str,
                    timeout: float = 120.0) -> None:
    """Pre-flight: every endpoint must answer a minimal chat request for `model` BEFORE
    selection starts. Any failure -> print all failing endpoints and abort the run.
    (Endpoints dying mid-run are handled by retries -> the question becomes status=failed.)"""
    import sys
    bad = []
    for url in _split_base_urls(base_url):
        try:
            client = OpenAI(base_url=url, api_key=api_key, timeout=timeout, max_retries=0)
            resp = client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": "Reply with OK."}],
                max_tokens=4, temperature=0)
            # with a reasoning parser and thinking on, 4 tokens all land in `reasoning`
            msg = resp.choices[0].message if resp.choices else None
            extra = (getattr(msg, "model_extra", None) or {}) if msg is not None else {}
            if msg is None or (msg.content is None and not getattr(msg, "reasoning_content", None)
                               and not extra.get("reasoning_content") and not extra.get("reasoning")):
                raise RuntimeError("empty response")
            print(f"[endpoint ok] {tag}: {url} model={model}", flush=True)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{url}: {type(exc).__name__}: {str(exc)[:200]}")
    if bad:
        msg = (f"[FATAL] {tag} endpoint check failed (model={model}); fix the server(s) and retry:\n  - "
               + "\n  - ".join(bad))
        print(msg, flush=True)
        print(msg, file=sys.stderr, flush=True)
        sys.exit(3)


class EndpointPool:
    """Least-connections pool over multiple OpenAI-compatible vLLM endpoints.

    - Each endpoint gets its own OpenAI client with an explicit short timeout
      (replacing the SDK default of 600s) and max_retries=0 (we do our own
      cross-endpoint failover instead of retrying the same dead host).
    - chat()/generate() pick the endpoint with the fewest in-flight requests,
      so a slow endpoint naturally receives fewer tasks (kills the head-of-line
      "bucket" effect that made static sharding wait on the slowest shard).
    - On failure/timeout the request fails over to the next-best endpoint up to
      `max_failover` times. An endpoint that fails repeatedly is cooled down for
      a short window so it stops being picked.
    """

    def __init__(
        self,
        base_urls: Union[str, List[str]],
        api_key: str,
        *,
        timeout: float = 90.0,
        max_failover: int = 2,
        cooldown_sec: float = 30.0,
        cooldown_after_fails: int = 3,
        slow_factor: float = 0.0,
        slow_min_sec: float = 8.0,
    ) -> None:
        self.urls = _split_base_urls(base_urls)
        self.timeout = timeout
        self.max_failover = max_failover
        self.cooldown_sec = cooldown_sec
        self.cooldown_after_fails = cooldown_after_fails
        # latency circuit-breaker: an endpoint whose EWMA latency exceeds
        # slow_factor * (fastest endpoint's EWMA) AND > slow_min_sec gets cooled
        # down, so a contended/slow host stops being picked even if it "works".
        self.slow_factor = slow_factor
        self.slow_min_sec = slow_min_sec
        self._lock = threading.Lock()
        # Bounded httpx pool per endpoint: enough connections for our per-endpoint
        # concurrency, with keepalive reuse so we don't churn sockets/threads.
        per_ep_conns = int(os.environ["TAKA_LLM_MAX_CONN_PER_EP"])
        self._clients = [
            OpenAI(
                api_key=api_key, base_url=u, timeout=timeout, max_retries=0,
                http_client=httpx.Client(
                    limits=httpx.Limits(
                        max_connections=per_ep_conns,
                        max_keepalive_connections=per_ep_conns,
                        keepalive_expiry=30.0,
                    ),
                    timeout=timeout,
                ),
            )
            for u in self.urls
        ]
        n = len(self.urls)
        self._inflight = [0] * n
        self._fails = [0] * n
        self._cooldown_until = [0.0] * n
        self._ewma = [0.0] * n  # EWMA request latency (0 = no data yet)

    def __len__(self) -> int:
        return len(self.urls)

    def _pick(self, exclude: set) -> int:
        """Pick endpoint with fewest in-flight requests (least-connections),
        tie-broken by lower EWMA latency. Skips cooled-down/already-tried
        endpoints; falls back to ignoring cooldown if all are cooling."""
        now = time.time()
        with self._lock:
            cands = [
                i for i in range(len(self.urls))
                if i not in exclude and self._cooldown_until[i] <= now
            ]
            if not cands:  # all cooling/excluded -> ignore cooldown, keep exclude
                cands = [i for i in range(len(self.urls)) if i not in exclude]
            if not cands:  # everything excluded -> reuse all (last resort)
                cands = list(range(len(self.urls)))
            idx = min(cands, key=lambda i: (self._inflight[i], self._ewma[i]))
            self._inflight[idx] += 1
        return idx

    def _release(self, idx: int, ok: bool, latency: float = 0.0) -> None:
        with self._lock:
            self._inflight[idx] = max(0, self._inflight[idx] - 1)
            if ok:
                self._fails[idx] = 0
                # update EWMA latency (used as a tie-breaker in _pick)
                prev = self._ewma[idx]
                self._ewma[idx] = latency if prev <= 0 else 0.7 * prev + 0.3 * latency
                # OPTIONAL latency circuit-breaker (OFF by default: slow_factor<=0).
                # When ALL endpoints carry baseline load and latency merely
                # fluctuates (1-15s), cooling "relatively slow but usable" ones
                # starves most of the cluster — pure least-connections is correct
                # there (a slow endpoint accrues in-flight and is picked less, but
                # never fully idled). Only enable for genuinely-broken hosts.
                if self.slow_factor > 0:
                    live = [e for e in self._ewma if e > 0]
                    if live:
                        best = min(live)
                        if self._ewma[idx] > self.slow_min_sec and self._ewma[idx] > self.slow_factor * best:
                            self._cooldown_until[idx] = time.time() + self.cooldown_sec
            else:
                self._fails[idx] += 1
                if self._fails[idx] >= self.cooldown_after_fails:
                    self._cooldown_until[idx] = time.time() + self.cooldown_sec

    def create(self, **kwargs):
        """Run chat.completions.create with least-conn selection + failover.
        Returns the response object. Raises the last error if all attempts fail."""
        tried: set = set()
        last_err = None
        attempts = min(self.max_failover + 1, len(self.urls))
        for _ in range(attempts):
            idx = self._pick(tried)
            tried.add(idx)
            ok = False
            t0 = time.time()
            try:
                resp = self._clients[idx].chat.completions.create(**kwargs)
                ok = True
                return resp
            except Exception as e:  # noqa: BLE001 - failover on any client/transport error
                last_err = e
            finally:
                self._release(idx, ok, time.time() - t0)
        raise last_err if last_err is not None else RuntimeError("EndpointPool: no endpoints")


def _encode_image(img: Union[Image.Image, str]) -> dict:
    """将 PIL.Image 或 base64 字符串编码为 OpenAI image_url 格式。"""
    if isinstance(img, str):
        url = f"data:image/jpeg;base64,{img}"
    else:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        url = f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"
    return {"type": "image_url", "image_url": {"url": url}}


def _pool_from_config(config: Dict, tag: str) -> EndpointPool:
    """Build an EndpointPool from a config dict. base_url may be a single URL,
    a comma-separated string, or a list. Tunables overridable via env."""
    timeout = float(config.get("timeout") or os.environ["TAKA_LLM_TIMEOUT"])
    max_failover = int(config.get("max_failover") or os.environ["TAKA_LLM_FAILOVER"])
    pool = EndpointPool(
        config["base_url"], config["api_key"],
        timeout=timeout, max_failover=max_failover,
        cooldown_sec=float(os.environ["TAKA_LLM_COOLDOWN"]),
        cooldown_after_fails=int(os.environ["TAKA_LLM_COOLDOWN_FAILS"]),
        slow_factor=float(os.environ["TAKA_LLM_SLOW_FACTOR"]),
        slow_min_sec=float(os.environ["TAKA_LLM_SLOW_MIN_SEC"]),
    )
    print(f"[{tag}] {len(pool)} endpoint(s), timeout={timeout}s, failover={max_failover}, "
          f"slow_factor={pool.slow_factor}, slow_min={pool.slow_min_sec}s: {pool.urls}")
    return pool


class LLMofAgent:
    """Agent model: autonomously decides which frames to select."""
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._pool = _pool_from_config(self.config, "Agent LLM")
        self._call_state = threading.local()
        print(f"[Agent LLM] Initializing with model: {self.config.get('model_name', 'N/A')}")

    def pop_last_usage(self) -> Dict[str, Optional[int]]:
        """Return and clear token usage (plus finish_reason and the model's reasoning text,
        for trajectory records) of the current thread's latest chat call."""
        usage = getattr(self._call_state, "usage", None)
        self._call_state.usage = None
        return usage or {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }

    def _remember_usage(self, response) -> None:
        usage = getattr(response, "usage", None)
        choice = (getattr(response, "choices", None) or [None])[0]
        message = getattr(choice, "message", None)
        reasoning = getattr(message, "reasoning_content", None)
        if reasoning is None and message is not None:
            extra = getattr(message, "model_extra", None) or {}
            reasoning = extra.get("reasoning_content") or extra.get("reasoning")
        self._call_state.usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
            "finish_reason": getattr(choice, "finish_reason", None),
            "reasoning": reasoning,
        }

    def generate(
        self,
        prompt: str,
        images: Optional[List[Union[Image.Image, str]]] = None,
    ) -> str:
        """
        Generate text. If images provided, send as multimodal (vision) input.
        images: list of PIL.Image or base64 strings.
        """
        content: list = [{"type": "text", "text": prompt}]
        if images:
            content.extend(_encode_image(img) for img in images)
        response = self._pool.create(
            model=self.config["model_name"],
            messages=[{"role": "user", "content": content}],
            temperature=self.config.get("temperature", 0.7),
            max_tokens=self.config.get("max_tokens", 2048),
            extra_body=_extra_body(),
            **_sampling_kwargs(self.config),
        )
        return response.choices[0].message.content

    def chat(
        self,
        messages: List[Dict],
        *,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        override_top_p: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> Union[str, Dict[str, Any]]:
        """Multi-turn chat. messages: [{"role": str, "content": str|list}, ...]"""
        self._call_state.usage = None
        # Persisted trajectories keep OpenAI-style ``reasoning`` separate from an
        # empty assistant ``content``. Qwen3-VL's stock chat template renders
        # tool_calls/tool messages but ignores the non-standard reasoning field.
        # Populate content only in the wire copy so the next model turn still sees
        # the Evidence Ledger; the saved conversation remains content="" + reasoning.
        wire_messages = copy.deepcopy(messages)
        for msg in wire_messages:
            if (msg.get("role") == "assistant" and msg.get("tool_calls")
                    and not msg.get("content") and msg.get("reasoning")):
                msg["content"] = msg["reasoning"]
        request = dict(
            model=self.config["model_name"],
            messages=wire_messages,
            temperature=(self.config.get("temperature", 0.7)
                         if temperature is None else temperature),
            max_tokens=(self.config.get("max_tokens", 2048)
                        if max_tokens is None else max_tokens),
            extra_body=_extra_body(),
            **_sampling_kwargs({
                **self.config,
                "top_p": top_p if override_top_p else self.config.get("top_p"),
            }),
        )
        if tools:
            request["tools"] = tools
            if tool_choice is not None:
                request["tool_choice"] = tool_choice
        response = self._pool.create(**request)
        self._remember_usage(response)
        message = response.choices[0].message
        if not tools:
            return message.content

        # Preserve the model's native tool-call envelope instead of reconstructing
        # one from a project-specific JSON action.
        native_calls = []
        for call in message.tool_calls or []:
            native_calls.append({
                "id": call.id,
                "type": call.type or "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            })
        reasoning = getattr(message, "reasoning_content", None)
        if reasoning is None:
            extra = getattr(message, "model_extra", None) or {}
            reasoning = extra.get("reasoning_content") or extra.get("reasoning")
        return {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": native_calls,
            "reasoning": reasoning or message.content or "",
        }


class LLMofTest:
    """Test model: answers question based on selected frames (vision)."""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._pool = _pool_from_config(self.config, "Test LLM")
        print(f"[Test LLM] Initializing with model: {self.config.get('model_name', 'N/A')}")

    def answer(
        self,
        images: List[Union[Image.Image, str]],
        question: str,
    ) -> str:
        """Generate answer from frames + question."""
        prompt = f"Based on the keyframes above (in chronological order), answer the following question.\n\nQuestion: {question}\n\nAnswer:"
        return self.generate(prompt, images=images)

    def generate(
        self,
        prompt: str,
        images: Optional[List[Union[Image.Image, str]]] = None,
    ) -> str:
        """Same as LLMofAgent.generate, uses TEST_MODEL config."""
        content: list = [{"type": "text", "text": prompt}]
        if images:
            content.extend(_encode_image(img) for img in images)
        response = self._pool.create(
            model=self.config["model_name"],
            messages=[{"role": "user", "content": content}],
            temperature=self.config.get("temperature", 0.7),
            max_tokens=self.config.get("max_tokens", 2048),
            extra_body=_extra_body(),
            **_sampling_kwargs(self.config),
        )
        return response.choices[0].message.content
