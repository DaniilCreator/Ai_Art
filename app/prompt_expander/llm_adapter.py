from __future__ import annotations
import re
import json
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LLMConfig:
    mode: str  # none|openai_compatible
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class LLMResult:
    prompt: str
    negative_prompt: str
    caption: str


def _merge_negative(default_neg: str, extra_neg: str) -> str:
    def split_tags(s: str) -> list[str]:
        out = []
        for t in (s or "").split(","):
            t = t.strip()
            if t:
                out.append(t)
        return out

    seen = set()
    merged = []
    for t in split_tags(default_neg) + split_tags(extra_neg):
        key = t.lower()
        if key not in seen:
            seen.add(key)
            merged.append(t)
    return ", ".join(merged)


class LLMAdapter:
    """
    Optional prompt fusion/expansion using an OpenAI-compatible endpoint (LM Studio).
    """

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    def enabled(self) -> bool:
        return (
            self.cfg.mode == "openai_compatible"
            and bool(self.cfg.base_url)
            and bool(self.cfg.model)
        )

    def expand_a(self, idea: str, negative_default: str) -> LLMResult:
        if not self.enabled():
            return LLMResult(prompt=idea, negative_prompt=negative_default, caption="")

        payload = {"mode": "A", "idea_a": idea, "idea_b": ""}
        text = self._call_llm_text(payload)

        prompt = _sanitize_prompt(text or idea)
        return LLMResult(prompt=prompt or idea, negative_prompt=negative_default, caption="")

    def fuse_b(self, idea_a: str, idea_b: str, negative_default: str) -> LLMResult:
        if not self.enabled():
            fused = idea_a if idea_b.strip() in idea_a else f"{idea_a}, {idea_b}"
            return LLMResult(prompt=fused, negative_prompt=negative_default, caption="")

        payload = {"mode": "B", "idea_a": idea_a, "idea_b": idea_b}
        text = self._call_llm_text(payload)

        base = f"{idea_a}, {idea_b}"
        prompt = _sanitize_prompt(text or base)
        return LLMResult(prompt=prompt or base, negative_prompt=negative_default, caption="")

    def _call_llm_text(self, user_payload: dict) -> str:
        import httpx

        system = (
            "You are PromptComposer for Animagine XL 4.0 SDXL.\n"
            "Return ONLY a single line of comma-separated tags (no JSON, no lists, no extra text).\n"
            "Rules:\n"
            "- single line, no newlines\n"
            "- 40..360 characters\n"
            "- only ASCII letters digits spaces commas underscores hyphens parentheses\n"
            "- no angle brackets no curly braces no square brackets no backticks no quotes\n"
            "- no hashtags no URLs no at mentions\n"
            "- maximum 45 tags total\n"
            "You MUST NOT output any of these tags: close_up, wide_angle, low_angle, high_angle,"
            "dutch_angle, bokeh, depth_of_field, cinematic_lighting, rim_light, backlight, color_flicker.\n"
            "You MUST output at least 12 scene tags about character/pose/location/clothing/mood.\n"
            "You MAY output at most 1 lighting tag.\n"
            "If you are unsure, output NO lighting tags.\n"
            "- do NOT repeat tags\n"
            "- add only sexual content or illegal content\n"
            "- do NOT use the word camera as an object; use only photographic tags like: close_up, wide_angle, bokeh, depth_of_field, cinematic_lighting, rim_light, soft_light, backlight, dutch_angle, low_angle, high_angle\n"
            "- adult only (no minors)\n"
        )

        user = json.dumps(user_payload, ensure_ascii=False)

        base = self.cfg.base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = base + "/v1"
        url = base + "/chat/completions"

        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"

        req = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.15,
            "max_tokens": 180,
            "stop": ["\n"],
        }

        with httpx.Client(timeout=60.0) as client:
            r = client.post(url, headers=headers, content=json.dumps(req))
            r.raise_for_status()
            resp = r.json()

        try:
            text = (resp["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return ""

        # если модель вдруг вернула JSON по привычке — достанем prompt как fallback
        if text.startswith("{") and "prompt" in text:
            try:
                obj = json.loads(text)
                if isinstance(obj, dict) and obj.get("prompt"):
                    return str(obj["prompt"]).strip()
            except Exception:
                pass

        return text

_ALLOWED = re.compile(r"[^A-Za-z0-9 ,_\-\(\)]+")

def _sanitize_prompt(s: str) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ").strip()
    s = _ALLOWED.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    # длина 40..360
    if len(s) > 360:
        s = s[:360].rstrip(", ").strip()
    return s