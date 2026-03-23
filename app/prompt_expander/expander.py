from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from app.prompt_bank.topic_selector import SelectedCards
from app.prompt_expander.llm_adapter import LLMAdapter


@dataclass(frozen=True)
class ExpandedPrompt:
    prompt_text: str
    negative_prompt: str
    prompt_ids: List[str]  # IDs used (1 or 2)


def _load_weighted_lines(path: Path) -> List[Tuple[int, str]]:
    if not path.exists():
        return [(1, "1girl")]
    lines: List[Tuple[int, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        if "|" in raw:
            w_s, txt = raw.split("|", 1)
            try:
                w = int(w_s.strip())
            except Exception:
                w = 1
            txt = txt.strip()
            if txt:
                lines.append((max(1, w), txt))
        else:
            lines.append((1, raw))
    return lines or [(1, "1girl")]


def _weighted_choice(items: List[Tuple[int, str]]) -> str:
    weights = [w for w, _ in items]
    values = [v for _, v in items]
    return random.choices(values, weights=weights, k=1)[0]


class PromptExpander:
    """Expands a picked prompt idea into a final prompt.

    - Replaces {{subj1}}, {{subj2}}, {{subj3}} using weighted subject lists.
    - Mode A: single idea -> optional LLM rewrite.
    - Mode B: two ideas -> optional LLM fusion.
    """

    SUBJ_PATTERN = re.compile(r"\{\{\s*(subj[123])\s*\}\}")

    def __init__(self,
                 subjects_1: Path,
                 subjects_2: Path,
                 subjects_3: Path,
                 negative_default: str,
                 llm: LLMAdapter,
                 animagine_rating: str = ""):
        self.subj1 = _load_weighted_lines(subjects_1)
        self.subj2 = _load_weighted_lines(subjects_2)
        self.subj3 = _load_weighted_lines(subjects_3)
        self.negative_default = negative_default
        self.llm = llm
        self.animagine_rating = (animagine_rating or "").strip()

    def expand(self, selected: SelectedCards, negative_override: str | None = None) -> ExpandedPrompt:
        if selected.mode == "A" or selected.mix is None:
            base = self._apply_subjects(selected.primary.text)
            res = self.llm.expand_a(base, self.negative_default)
            return ExpandedPrompt(
                prompt_text=self._apply_rating(self._normalize(res.prompt)),
                negative_prompt=res.negative_prompt,
                prompt_ids=[selected.primary.id],
            )

        a = self._apply_subjects(selected.primary.text)
        b = self._apply_subjects(selected.mix.text)
        res = self.llm.fuse_b(a, b, self.negative_default)

        return ExpandedPrompt(
            prompt_text=self._apply_rating(self._normalize(res.prompt)),
            negative_prompt=res.negative_prompt,
            prompt_ids=[selected.primary.id, selected.mix.id],
        )

    def _apply_rating(self, prompt: str) -> str:
        """Prepend Animagine-style rating tag if provided and missing."""
        rating = self.animagine_rating
        if not rating:
            return prompt
        low = prompt.lower()
        if rating.lower() in low:
            return prompt
        return f"{rating}, {prompt}"

    def _apply_subjects(self, s: str) -> str:
        # choose once per call for consistency
        subj_map: Dict[str, str] = {
            "subj1": _weighted_choice(self.subj1),
            "subj2": _weighted_choice(self.subj2),
            "subj3": _weighted_choice(self.subj3),
        }

        def repl(m: re.Match[str]) -> str:
            key = m.group(1)
            return subj_map.get(key, "1girl")

        return self.SUBJ_PATTERN.sub(repl, s)

    @staticmethod
    def _normalize(s: str) -> str:
        # light normalization: collapse spaces and duplicate commas
        s = s.replace("\n", " ").replace("\r", " ")
        s = re.sub(r"\s+", " ", s)
        s = re.sub(r"\s*,\s*", ", ", s)
        s = re.sub(r",\s*,+", ", ", s)
        return s.strip(" ,")