from __future__ import annotations

import random
import re
from dataclasses import dataclass

from app.prompt_bank.loader import PromptCard
from app.prompt_bank.prompt_bank import PromptBank


@dataclass(frozen=True)
class SelectedCards:
    mode: str            # "A" or "B"
    primary: PromptCard
    mix: PromptCard | None


class TopicSelector:
    """Select prompt cards for Mode A/B using content/modifier topic split."""

    def __init__(self, bank: PromptBank, modifier_topic_regex: str,
                 mode_a_weight: float = 0.5):
        self.bank = bank
        self.mod_re = re.compile(modifier_topic_regex)
        self.mode_a_weight = max(0.0, min(1.0, float(mode_a_weight)))

    def _pick_mode(self, mode: str) -> str:
        m = (mode or "").upper().strip()
        if m in ("A", "B"):
            return m
        return "A" if random.random() < self.mode_a_weight else "B"

    def _split_topics(self) -> tuple[list[str], list[str]]:
        topics = self.bank.db.list_topics()
        modifier = [t for t in topics if self.mod_re.search(t)]
        content = [t for t in topics if not self.mod_re.search(t)]
        if not content:
            content = topics
        return content, modifier

    def select(self, forced_mode: str, avoid_prompt_ids: set[str]) -> SelectedCards:
        chosen_mode = self._pick_mode(forced_mode)
        content_topics, modifier_topics = self._split_topics()

        if not content_topics:
            raise RuntimeError("No topics found in DB. Did you /reload_prompts?")

        # MODE A: one card from content
        topic_a = random.choice(content_topics)
        primary = self.bank.pick_from_topic(topic_a, avoid_ids=avoid_prompt_ids)
        if primary is None:
            # fallback: try any content topic
            for _ in range(10):
                topic_a = random.choice(content_topics)
                primary = self.bank.pick_from_topic(topic_a, avoid_ids=set())
                if primary:
                    break
        if primary is None:
            raise RuntimeError("No prompts available for Mode A.")

        if chosen_mode == "A" or not modifier_topics:
            return SelectedCards(mode="A", primary=primary, mix=None)

        # MODE B: one modifier card
        topic_b = random.choice(modifier_topics)
        mix = self.bank.pick_from_topic(topic_b, avoid_ids=avoid_prompt_ids | {primary.id})
        if mix is None:
            # fallback: degrade to Mode A
            return SelectedCards(mode="A", primary=primary, mix=None)

        return SelectedCards(mode="B", primary=primary, mix=mix)
