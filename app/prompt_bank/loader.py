from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class PromptIdea:
    topic: str
    subtopic: str
    text: str


@dataclass(frozen=True)
class PromptCard:
    id: str
    topic: str
    subtopic: str
    text: str


def load_prompts_json(path: str | Path) -> List[PromptIdea]:
    """Load prompt ideas from JSON.

    Expected MVP format:
    {
      "Face Expressions": {
        "Shocked Face": "1girl, shocked, ...",
        "Angry": ["...", "..."]
      },
      "Camera Settings": {...}
    }

    Notes:
    - Leaves can be a string OR a list of strings.
    - JSON does NOT contain categories/tags.
    """
    p = Path(path)
    data: Dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))

    out: List[PromptIdea] = []
    for topic, sub in data.items():
        if not isinstance(sub, dict):
            continue
        for subtopic, leaf in sub.items():
            if isinstance(leaf, str):
                ideas = [leaf]
            elif isinstance(leaf, list):
                ideas = [x for x in leaf if isinstance(x, str)]
            else:
                ideas = []

            for txt in ideas:
                txt = (txt or "").strip()
                if txt:
                    out.append(PromptIdea(topic=str(topic).strip(), subtopic=str(subtopic).strip(), text=txt))

    return out
