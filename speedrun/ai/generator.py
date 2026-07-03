"""Transfer-question generator.

Given a NAMED SOURCE unit, ask Claude to produce new exam-style MCAT MCQs that
test the SAME idea in DIFFERENT WORDS (the paraphrase / transfer test, 7d).
Every produced item carries the source_id + citation so it is traceable.

This is the ONLY step that needs ANTHROPIC_API_KEY. It is defensive: on a
missing key, a missing SDK, an API error, or unparseable output, it logs a
clear message and FALLS BACK to the committed cached ``artifacts/generated.json``
so the rest of the pipeline (check/eval/baselines/leakage/paraphrase) still runs
deterministically with the AI off.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

from . import config
from . import items as items_mod
from .items import GeneratedItem
from .sources import SourceUnit, load_sources

log = logging.getLogger("speedrun.ai.generator")

SYSTEM_PROMPT = (
    "You are an MCAT item writer. Given a short NAMED SOURCE passage, write new "
    "multiple-choice questions that test the SAME underlying concept as the "
    "source but in DIFFERENT WORDS -- a transfer question, not a restatement. "
    "Rules:\n"
    "- Exactly 4 answer choices, exactly one clearly correct.\n"
    "- The correct answer and rationale must be supported by the source text.\n"
    "- Do NOT copy the source's sentences; rephrase the scenario.\n"
    "- Distractors must be plausible but clearly wrong.\n"
    "- Output ONLY valid JSON: a list of objects with keys "
    "stem, choices (list of 4 strings), answer_index (0-3), rationale, "
    "transfer_tags (list of short strings). No prose, no code fences."
)

# Few-shot examples are written from scratch (NOT copied from the gold/test set)
# so the leakage scan comes back clean. Kept generic and clearly paraphrased.
FEW_SHOT: List[Tuple[str, List[dict]]] = [
    (
        "Water boils at 100 degrees Celsius at one atmosphere of pressure because "
        "that is the temperature at which its vapor pressure equals atmospheric "
        "pressure.",
        [
            {
                "stem": "At sea level, a pot of water begins to boil. What condition "
                "has its vapor pressure just reached?",
                "choices": [
                    "It equals the surrounding atmospheric pressure",
                    "It falls to exactly zero",
                    "It exceeds the critical pressure of water",
                    "It becomes independent of temperature",
                ],
                "answer_index": 0,
                "rationale": "Boiling occurs when a liquid's vapor pressure equals "
                "the external atmospheric pressure.",
                "transfer_tags": ["rephrased-scenario", "concept:boiling-point"],
            }
        ],
    )
]


def build_user_prompt(unit: SourceUnit, n: int) -> str:
    return (
        "NAMED SOURCE (id={sid}, citation={cite}):\n"
        '"""{text}"""\n\n'
        "Write {n} transfer question(s) as described. Remember: rephrase, do not "
        "copy the wording above. Output ONLY the JSON list."
    ).format(sid=unit.source_id, cite=unit.citation, text=unit.text, n=n)


def collect_generator_inputs(units: List[SourceUnit], n_per_source: int = 1) -> List[str]:
    """All text fed to the model (system, few-shot, per-source prompts). The
    leakage scanner checks these against the held-out test set."""
    inputs: List[str] = [SYSTEM_PROMPT]
    for src_text, outs in FEW_SHOT:
        inputs.append(src_text)
        inputs.append(json.dumps(outs))
    for u in units:
        inputs.append(build_user_prompt(u, n_per_source))
    return inputs


def _extract_json(text: str) -> Optional[object]:
    """Best-effort extraction of a JSON array/object from model text."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        # strip code fences
        t = t.strip("`")
        if "\n" in t:
            t = t.split("\n", 1)[1]
    # Try direct parse first.
    try:
        return json.loads(t)
    except Exception:
        pass
    # Fall back to slicing between the first '[' and last ']' (or braces).
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = t.find(open_ch)
        end = t.rfind(close_ch)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(t[start : end + 1])
            except Exception:
                continue
    return None


def _parse_items(payload: object, unit: SourceUnit, start_idx: int) -> List[GeneratedItem]:
    raw: List[dict]
    if isinstance(payload, list):
        raw = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        raw = [payload]
    else:
        return []
    out: List[GeneratedItem] = []
    for j, d in enumerate(raw):
        d = dict(d)
        d.setdefault("source_id", unit.source_id)
        d.setdefault("citation", unit.citation)
        d.setdefault("origin", "claude")
        out.append(
            GeneratedItem.from_dict(d, default_id="gen-{}-{}".format(unit.source_id, start_idx + j))
        )
    return out


class LLMClient:
    """A thin provider-agnostic wrapper.

    ``provider`` is "anthropic" or "gemini". ``handle`` is the SDK object
    (Anthropic) or a ``callable(prompt_text) -> str`` (Gemini). ``model`` is the
    actual model name used, so meta/reporting stays honest about what ran.
    """

    def __init__(self, provider: str, handle, model: str):
        self.provider = provider
        self.handle = handle
        self.model = model


def _run_with_retries(unit: SourceUnit, run):
    """Call ``run()`` (returns model text) with retries + graceful degrade."""
    last_err: Optional[Exception] = None
    for attempt in range(1, config.GENERATE_MAX_RETRIES + 1):
        try:
            text = run()
            payload = _extract_json(text)
            if payload is not None:
                return payload
            last_err = ValueError("could not parse JSON from model output")
        except Exception as e:  # noqa: BLE001 - we intentionally degrade gracefully
            last_err = e
        sleep_s = config.GENERATE_BACKOFF_SECONDS * attempt
        log.warning(
            "generation attempt %d/%d failed for %s (%s); backing off %.1fs",
            attempt,
            config.GENERATE_MAX_RETRIES,
            unit.source_id,
            last_err,
            sleep_s,
        )
        time.sleep(sleep_s)
    return None


def _call_anthropic(client: LLMClient, unit: SourceUnit, n: int) -> Optional[object]:
    messages = []
    for src_text, outs in FEW_SHOT:
        messages.append({"role": "user", "content": build_user_prompt(
            SourceUnit(source_id="example", citation="example", text=src_text), n)})
        messages.append({"role": "assistant", "content": json.dumps(outs)})
    messages.append({"role": "user", "content": build_user_prompt(unit, n)})

    def run() -> str:
        resp = client.handle.messages.create(
            model=client.model,
            max_tokens=config.GENERATE_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        return "".join(
            getattr(block, "text", "") for block in getattr(resp, "content", [])
        )

    return _run_with_retries(unit, run)


def _gemini_prompt(unit: SourceUnit, n: int) -> str:
    """Single-string prompt with the few-shot examples inlined."""
    parts: List[str] = []
    for src_text, outs in FEW_SHOT:
        parts.append(build_user_prompt(
            SourceUnit(source_id="example", citation="example", text=src_text), n))
        parts.append("Example output JSON:\n" + json.dumps(outs))
    parts.append(build_user_prompt(unit, n))
    return "\n\n".join(parts)


def _call_gemini(client: LLMClient, unit: SourceUnit, n: int) -> Optional[object]:
    prompt = _gemini_prompt(unit, n)
    return _run_with_retries(unit, lambda: client.handle(prompt))


def _call_groq(client: LLMClient, unit: SourceUnit, n: int) -> Optional[object]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for src_text, outs in FEW_SHOT:
        messages.append({"role": "user", "content": build_user_prompt(
            SourceUnit(source_id="example", citation="example", text=src_text), n)})
        messages.append({"role": "assistant", "content": json.dumps(outs)})
    messages.append({"role": "user", "content": build_user_prompt(unit, n)})

    def run() -> str:
        resp = client.handle.chat.completions.create(
            model=client.model,
            messages=messages,
            max_tokens=config.GENERATE_MAX_TOKENS,
            temperature=0.7,
        )
        return resp.choices[0].message.content or ""

    return _run_with_retries(unit, run)


def _call_claude(client, model: str, unit: SourceUnit, n: int) -> Optional[object]:
    """Back-compat dispatcher (name kept). Routes to the right provider."""
    if isinstance(client, LLMClient):
        if client.provider == "gemini":
            return _call_gemini(client, unit, n)
        if client.provider == "groq":
            return _call_groq(client, unit, n)
        return _call_anthropic(client, unit, n)
    # Legacy: a raw Anthropic client was passed in.
    return _call_anthropic(LLMClient("anthropic", client, model), unit, n)


def _load_anthropic_client(model: str) -> Optional[LLMClient]:
    api_key = os.environ.get(config.API_KEY_ENV)
    if not api_key:
        return None
    try:
        import anthropic  # type: ignore
    except Exception as e:  # noqa: BLE001
        log.warning("anthropic SDK not importable (%s).", e)
        return None
    try:
        handle = anthropic.Anthropic(api_key=api_key, timeout=config.GENERATE_TIMEOUT_SECONDS)
        return LLMClient("anthropic", handle, model)
    except Exception as e:  # noqa: BLE001
        log.warning("could not construct Anthropic client (%s).", e)
        return None


def _load_gemini_client(model_name: str) -> Optional[LLMClient]:
    api_key = os.environ.get(config.GEMINI_API_KEY_ENV) or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None
    # Prefer the new google-genai SDK; fall back to google-generativeai.
    try:
        from google import genai as _genai  # type: ignore

        cli = _genai.Client(
            api_key=api_key,
            http_options={"timeout": int(config.GENERATE_TIMEOUT_SECONDS * 1000)},
        )

        def _run(prompt: str) -> str:
            resp = cli.models.generate_content(
                model=model_name,
                contents=SYSTEM_PROMPT + "\n\n" + prompt,
            )
            return getattr(resp, "text", "") or ""

        return LLMClient("gemini", _run, model_name)
    except Exception:  # noqa: BLE001 - try the other SDK
        pass
    try:
        import google.generativeai as _genai  # type: ignore

        _genai.configure(api_key=api_key)
        gm = _genai.GenerativeModel(model_name, system_instruction=SYSTEM_PROMPT)

        def _run(prompt: str) -> str:
            resp = gm.generate_content(
                prompt,
                generation_config={"max_output_tokens": config.GENERATE_MAX_TOKENS},
            )
            return getattr(resp, "text", "") or ""

        return LLMClient("gemini", _run, model_name)
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini SDK not usable (%s).", e)
        return None


def _load_groq_client(model_name: str) -> Optional[LLMClient]:
    api_key = os.environ.get(config.GROQ_API_KEY_ENV)
    if not api_key:
        return None
    try:
        from groq import Groq  # type: ignore

        handle = Groq(api_key=api_key, timeout=config.GENERATE_TIMEOUT_SECONDS)
        return LLMClient("groq", handle, model_name)
    except Exception as e:  # noqa: BLE001
        log.warning("Groq SDK not usable (%s).", e)
        return None


def _load_client(model: str):
    """Load a live client. Prefer Anthropic, then Gemini, then Groq (all
    free-tier friendly except Anthropic). Returns None if none is available, so
    callers degrade to the cached, gate-passed artifacts."""
    client = _load_anthropic_client(model)
    if client is not None:
        return client
    client = _load_gemini_client(config.GEMINI_MODEL)
    if client is not None:
        log.info("using Gemini model %s for live generation.", client.model)
        return client
    client = _load_groq_client(config.GROQ_MODEL)
    if client is not None:
        log.info("using Groq model %s for live generation.", client.model)
        return client
    log.warning(
        "no AI provider configured (%s / %s / %s unset) -- using cached artifacts.",
        config.API_KEY_ENV,
        config.GEMINI_API_KEY_ENV,
        config.GROQ_API_KEY_ENV,
    )
    return None


def generate(
    n_per_source: int = 1,
    model: Optional[str] = None,
    include_collection: bool = True,
) -> List[GeneratedItem]:
    """Generate transfer questions for all source units and write
    ``artifacts/generated.json``. Falls back to the cached file on any failure.
    """
    model = model or config.DEFAULT_MODEL
    units = load_sources(include_collection=include_collection)
    if not units:
        log.warning("no source units found in %s -- using cached artifacts.", config.SOURCES_DIR)
        return _fallback("no sources")

    client = _load_client(model)
    if client is None:
        return _fallback("no client")
    # Report the model that actually ran (may be the Gemini fallback).
    model = getattr(client, "model", model)

    generated: List[GeneratedItem] = []
    failures = 0
    for i, unit in enumerate(units):
        payload = _call_claude(client, model, unit, n_per_source)
        if payload is None:
            failures += 1
            log.warning("giving up on source %s after retries", unit.source_id)
            continue
        parsed = _parse_items(payload, unit, start_idx=len(generated))
        generated.extend(parsed)

    if not generated:
        log.error("live generation produced nothing usable -- using cached artifacts.")
        return _fallback("empty generation")

    meta = {
        "model": model,
        "n_sources": len(units),
        "n_failures": failures,
        "note": "Live generation. Every item cites a named source.",
    }
    items_mod.write_generated(generated, sample=False, meta=meta)
    log.info("wrote %d generated items (%d source failures) to %s",
             len(generated), failures, config.GENERATED_PATH)
    return generated


def _fallback(reason: str) -> List[GeneratedItem]:
    cached = items_mod.load_generated()
    if cached:
        tag = "sample" if items_mod.is_sample_generated() else "cached"
        log.info("falling back to %d %s items (%s).", len(cached), tag, reason)
    else:
        log.error("no cached artifacts available to fall back to (%s).", reason)
    return cached
