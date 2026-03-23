from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.prompt_bank.loader import load_prompts_json, PromptCard, PromptIdea
from app.storage.db import DB


def make_prompt_id(topic: str, subtopic: str, text: str) -> str:
    s = f"{topic}||{subtopic}||{text}".encode("utf-8")
    return hashlib.sha1(s).hexdigest()


class PromptBank:
    def __init__(self, db: DB, prompts_path: str | Path):
        self.db = db
        self.prompts_path = str(prompts_path)

    def reload(self) -> int:
        ideas = load_prompts_json(self.prompts_path)
        for it in ideas:
            pid = make_prompt_id(it.topic, it.subtopic, it.text)
            self.db.upsert_prompt(pid=pid, topic=it.topic, subtopic=it.subtopic, base_idea=it.text)
        return len(ideas)

    def pick_from_topic(self, topic: str, avoid_ids: set[str]) -> PromptCard | None:
        row = self.db.pick_prompt_from_topic(topic=topic, avoid_ids=avoid_ids)
        if not row:
            return None
        return PromptCard(id=row.id, topic=row.topic, subtopic=row.subtopic, text=row.base_idea)
