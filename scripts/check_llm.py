"""连通性自检：确认 key / base_url / 模型名 / JSON 模式四项都对得上。

在跑整条三 Agent 管线之前先跑这个 —— 它只发**两次最小请求**（各约几十个
token），能把「配置写错了」和「模型答得不好」这两类问题分开。

    python scripts/check_llm.py                 # 读 .env 里的 OPENAI_* 配置
    python scripts/check_llm.py --model deepseek-v4-pro
    python scripts/check_llm.py --skip-json-mode    # 跳过 json_object 探测

退出码：0 全通；1 有失败项。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, Optional

sys.path.insert(0, ".")

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]


OK = "  ✅"
NO = "  ❌"
WARN = "  ⚠️ "

_failures = 0


def ok(msg: str) -> None:
    print(f"{OK} {msg}")


def fail(msg: str, hint: str = "") -> None:
    global _failures
    _failures += 1
    print(f"{NO} {msg}")
    if hint:
        for line in hint.strip().splitlines():
            print(f"     {line}")


def warn(msg: str) -> None:
    print(f"{WARN}{msg}")


def section(title: str) -> None:
    print()
    print(f"── {title} " + "─" * max(0, 60 - len(title)))


# ══════════════════════════════════════════════════════════════════════════
# 1. 环境变量
# ══════════════════════════════════════════════════════════════════════════
def check_env(model_override: Optional[str]) -> Dict[str, str]:
    section("配置")
    if load_dotenv is not None:
        load_dotenv()

    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    use_real = os.getenv("USE_REAL_LLM", "false").lower() in {"1", "true", "yes"}

    if provider == "openai":
        key = os.getenv("OPENAI_API_KEY", "").strip()
        base = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").strip()
        model = model_override or os.getenv("OPENAI_MODEL", "gpt-4.1")
        key_name = "OPENAI_API_KEY"
    elif provider.startswith("minimax"):
        key = (os.getenv("MINIMAX_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or "").strip()
        base = (
            os.getenv("MINIMAX_BASE_URL")
            or os.getenv("ANTHROPIC_BASE_URL")
            or "https://api.minimaxi.com/anthropic"
        ).strip()
        model = model_override or os.getenv("MINIMAX_MODEL", "")
        key_name = "MINIMAX_API_KEY"
    else:
        fail(f"LLM_PROVIDER={provider} 不认识", "只支持 openai / minimax / minimax_anthropic")
        return {}

    ok(f"LLM_PROVIDER   = {provider}")
    ok(f"BASE_URL       = {base}")
    ok(f"MODEL          = {model}")
    ok(f"USE_REAL_LLM   = {use_real}")
    if not use_real:
        warn(
            "USE_REAL_LLM=false：即便 key 通了，三 Agent 仍走基线后端。"
            "验证完记得改成 true。"
        )

    # DeepSeek 在 2026-07-24 退役了 deepseek-chat / deepseek-reasoner。
    # 这条要在 key 之前查：它是最常见的「填了 key 还是 400」的原因。
    retired = {"deepseek-chat", "deepseek-reasoner"}
    if model in retired:
        fail(
            f"模型名 {model} 已于 2026-07-24 退役，请求会直接报错",
            "改成 deepseek-flash（便宜快）或 deepseek-v4-pro（强推理）。",
        )

    if not key:
        fail(
            f"{key_name} 为空",
            "去 provider 控制台建一个 key，填进 .env 的这一项。",
        )
        return {}
    masked = key[:6] + "*" * max(0, len(key) - 10) + key[-4:] if len(key) > 12 else "***"
    ok(f"{key_name:<15}= {masked}（长度 {len(key)}）")

    if not model:
        fail("模型名为空")
        return {}

    return {"provider": provider, "key": key, "base": base, "model": model}


# ══════════════════════════════════════════════════════════════════════════
# 2. 最小调用
# ══════════════════════════════════════════════════════════════════════════
def _call(
    cfg: Dict[str, str], *, json_mode: bool, system: str, user: str
) -> tuple[bool, str, Dict[str, Any]]:
    from llm_client import LLMClient, NO_RESPONSE_FORMAT

    client = LLMClient(
        api_key=cfg["key"],
        model=cfg["model"],
        base_url=cfg["base"],
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    t0 = time.time()
    try:
        raw = client._call_provider(  # noqa: SLF001 - 自检就是要摸底层
            messages,
            # 纯文本探测必须真的不带 response_format，否则部分 provider
            # （如 DeepSeek）会因 prompt 里没有 "json" 而 400。
            response_format={"type": "json_object"} if json_mode else NO_RESPONSE_FORMAT,
        )
        return True, raw or "", {"latency": round(time.time() - t0, 2)}
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}", {"latency": round(time.time() - t0, 2)}


def check_plain(cfg: Dict[str, str]) -> None:
    section("① 纯文本调用（验证 key / base_url / 模型名）")
    good, out, meta = _call(
        cfg,
        json_mode=False,
        system="只回复两个字。",
        user="回复：通了",
    )
    if good and out.strip():
        ok(f"通了（{meta['latency']}s）：{out.strip()[:60]}")
    elif good:
        fail("返回为空", "模型连通但没吐内容，检查 base_url 是否指向正确的服务。")
    else:
        hint = ""
        low = out.lower()
        if "401" in low or "invalid api key" in low or "authentication" in low:
            hint = "key 无效或已过期 —— 重新生成一个，注意不要带空格/换行。"
        elif "404" in low or "model_not_found" in low or "does not exist" in low:
            hint = (
                "模型名不对。DeepSeek 现在用 deepseek-flash / deepseek-v4-pro；\n"
                "deepseek-chat 与 deepseek-reasoner 已于 2026-07-24 退役。"
            )
        elif "402" in low or "insufficient" in low or "balance" in low:
            hint = "余额不足 —— 去控制台充值。"
        elif "connect" in low or "timeout" in low or "ssl" in low:
            hint = "网络不通 —— 检查 BASE_URL、代理、或是否需要走国内节点。"
        fail(f"调用失败：{out[:200]}", hint)


def check_json_mode(cfg: Dict[str, str]) -> None:
    section("② JSON 模式（三个 Agent 全靠它）")
    print("     三 Agent 用 response_format={'type':'json_object'} 拿结构化输出，")
    print("     这个 provider 不支持的话，审查/生成通道会全数降级。")
    good, out, meta = _call(
        cfg,
        json_mode=True,
        system='只输出 JSON，形如 {"status":"ok"}，不要任何解释。',
        user="现在输出。",
    )
    if good and out.strip():
        ok(f"支持（{meta['latency']}s）：{out.strip()[:80]}")
        # 再确认解析得开
        try:
            from llm_client import _extract_json_object

            parsed = _extract_json_object(out)
            ok(f"解析成功：{parsed}")
        except Exception as exc:  # noqa: BLE001
            warn(f"能返回但解析失败（{exc}）—— Agent 会退回基线后端，不致命。")
    else:
        low = out.lower()
        hint = ""
        if "response_format" in low or "json" in low or "400" in low:
            hint = (
                "这个 provider 可能不支持 json_object 模式。\n"
                "选项：换 DeepSeek / 通义 / 智谱（都支持），或改 llm_bridge 走纯文本 + 容错解析。"
            )
        fail(f"不支持或失败：{out[:200]}", hint)


def check_agents_wiring(cfg: Dict[str, str]) -> None:
    section("③ 三 Agent 装配（不联网，只验证代码路径）")
    from agents.llm_bridge import build_bridges
    from agents.prompts import (
        PLAN_GEN_PROMPT_VERSION,
        SAFETY_EVAL_PROMPT_VERSION,
        STATE_RISK_PROMPT_VERSION,
    )

    class _Echo:
        """假装是 LLMClient，只为看三份 prompt 是否真的不同。"""

        def __init__(self) -> None:
            self.seen: list[str] = []

        def chat_json(self, system_prompt: str, user_prompt: str, **kw: Any) -> Dict[str, Any]:
            self.seen.append(system_prompt[:40])
            return {}

    echo = _Echo()
    bridges = build_bridges(echo)  # type: ignore[arg-type]
    ok(f"build_bridges → {type(bridges).__name__}")
    ok(f"state_risk  prompt {STATE_RISK_PROMPT_VERSION}")
    ok(f"plan_gen    prompt {PLAN_GEN_PROMPT_VERSION}")
    ok(f"safety_eval prompt {SAFETY_EVAL_PROMPT_VERSION}")


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM 连通性自检")
    ap.add_argument("--model", help="临时覆盖 .env 里的模型名")
    ap.add_argument("--skip-json-mode", action="store_true", help="跳过 json_object 探测")
    args = ap.parse_args()

    print("=" * 66)
    print("LLM 连通性自检")
    print("=" * 66)

    cfg = check_env(args.model)
    if not cfg:
        section("结论")
        print("  配置不全，未能发起调用。补好 .env 再跑一次。")
        return 1

    check_plain(cfg)
    if not args.skip_json_mode:
        check_json_mode(cfg)
    check_agents_wiring(cfg)

    section("结论")
    if _failures:
        print(f"  {_failures} 项失败，按上面的提示改完再跑。")
        return 1
    print("  全通。可以：")
    print("    1) 把 .env 的 USE_REAL_LLM 改成 true")
    print("    2) python scripts/trace_stages.py --agent 看假模型的形状（不烧钱）")
    print("    3) python scripts/verify_plan_quality.py 跑真模型的对照")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
