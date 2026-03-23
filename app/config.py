from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import random
load_dotenv()

def _parse_presets(s: str) -> list[tuple[int, int]]:
    """Parse presets like: "1024x1024,1344x768,768x1344"."""
    out: list[tuple[int, int]] = []
    for part in (s or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "x" not in part.lower():
            continue
        w_s, h_s = part.lower().split("x", 1)
        try:
            w = int(w_s.strip())
            h = int(h_s.strip())
        except Exception:
            continue
        if w > 0 and h > 0:
            out.append((w, h))
    return out


def pick_resolution(cfg: "AppConfig") -> tuple[int, int]:
    """Pick width/height for the next generation.

    - fixed: use cfg.width/cfg.height
    - random: random choice from cfg.resolution_presets (fallback to width/height)
    """
    mode = (cfg.resolution_mode or "fixed").strip().lower()
    if mode != "random":
        return int(cfg.width), int(cfg.height)
    if cfg.resolution_presets:
        return random.choice(cfg.resolution_presets)
    return int(cfg.width), int(cfg.height)


def _getenv(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


def _as_bool(v: str) -> bool:
    s = (v or "").strip().lower()
    return s in {"1", "true", "yes", "y", "on"}


def _as_int(v: str, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _as_float(v: str, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return default


@dataclass(frozen=True)
class AppConfig:
    # Telegram
    bot_token: str
    channel_id: str
    admin_ids: set[int]
    tg_send_as: str  # document|photo
    caption_template: str

    # Model / generation
    model_id: str
    dtype: str
    sampler: str
    steps: int
    cfg: float
    negative_default: str
    width: int
    height: int
    seed: int | None

    # Resolution presets
    resolution_mode: str  # fixed|random
    resolution_presets: list[tuple[int, int]]

    # Scheduler / runtime
    post_interval_min: int
    paused: bool

    # Paths
    data_dir: Path
    output_dir: Path
    db_path: Path
    hf_home: Path
    prompts_path: Path

    # Watermark/text filtering
    watermark_mode: str  # fast|strict
    reject_if_text_likely: bool

    # Optional NSFW filtering (off by default)
    nsfw_filter_enabled: bool

    # Prompting
    prompt_mode: str  # A|B|AB_RANDOM
    prompt_mode_a_weight: float
    modifier_topic_regex: str
    no_repeat_last_n: int

    # Subjects slots (optional)
    subjects_1_path: Path
    subjects_2_path: Path
    subjects_3_path: Path

    # LLM adapter (optional)
    llm_mode: str  # none|openai_compatible
    llm_base_url: str
    llm_api_key: str
    llm_model: str

    # Animagine XL extras (optional)
    animagine_rating: str

    @property
    def modifier_re(self) -> re.Pattern[str]:
        return re.compile(self.modifier_topic_regex)


def load_config() -> AppConfig:
    admin_raw = _getenv("ADMIN_IDS", "")
    admin_ids = set(int(x.strip()) for x in admin_raw.split(",") if x.strip())

    paused = _as_bool(_getenv("PAUSED", "false"))
    reject_if_text = _as_bool(_getenv("REJECT_IF_TEXT_LIKELY", "true"))

    data_dir = Path(_getenv("DATA_DIR", "./data")).resolve()
    output_dir = Path(_getenv("OUTPUT_DIR", "./data/outputs")).resolve()
    db_path = Path(_getenv("DB_PATH", "./data/db/app.db")).resolve()
    hf_home = Path(_getenv("HF_HOME", "./data/hf_cache")).resolve()

    prompts_path = Path(_getenv("PROMPTS_PATH", str(data_dir / "prompts.json"))).resolve()

    # Generation params
    width = _as_int(_getenv("WIDTH", "1024"), 1024)
    height = _as_int(_getenv("HEIGHT", "1024"), 1024)

    resolution_mode = _getenv("RESOLUTION_MODE", "fixed").strip().lower()
    resolution_presets = _parse_presets(_getenv("RESOLUTION_PRESETS", ""))

    seed_raw = _getenv("SEED", "")
    seed = int(seed_raw) if seed_raw.strip().isdigit() else None

    # Prompt modes
    prompt_mode = _getenv("PROMPT_MODE", "AB_RANDOM").upper().strip()
    if prompt_mode not in {"A", "B", "AB_RANDOM"}:
        prompt_mode = "AB_RANDOM"

    mode_a_weight = _as_float(_getenv("PROMPT_MODE_A_WEIGHT", "0.5"), 0.5)
    mode_a_weight = max(0.0, min(1.0, mode_a_weight))

    cfg = AppConfig(
        # Telegram
        bot_token=_getenv("BOT_TOKEN"),
        channel_id=_getenv("CHANNEL_ID"),
        admin_ids=admin_ids,
        tg_send_as=_getenv("TG_SEND_AS", "photo").strip().lower(),
        caption_template=_getenv("CAPTION_TEMPLATE", ""),

        # Model / generation
        model_id=_getenv("MODEL_ID", "gsdf/Counterfeit-V2.5"),
        dtype=_getenv("DTYPE", "float16"),
        sampler=_getenv("SAMPLER", "euler_a"),
        steps=_as_int(_getenv("STEPS", "24"), 24),
        cfg=float(_getenv("CFG", "5.5")),
        negative_default=_getenv("NEGATIVE_DEFAULT", ""),
        width=width,
        height=height,
        seed=seed,

        resolution_mode=resolution_mode,
        resolution_presets=resolution_presets,

        # Scheduler
        post_interval_min=_as_int(_getenv("POST_INTERVAL_MIN", "20"), 20),
        paused=paused,

        # Paths
        data_dir=data_dir,
        output_dir=output_dir,
        db_path=db_path,
        hf_home=hf_home,
        prompts_path=prompts_path,

        # Filters
        watermark_mode=_getenv("WATERMARK_MODE", "off").strip().lower(),
        reject_if_text_likely=reject_if_text,
        nsfw_filter_enabled=_as_bool(_getenv("NSFW_FILTER_ENABLED", "false")),

        # Prompting
        prompt_mode=prompt_mode,
        prompt_mode_a_weight=mode_a_weight,
        modifier_topic_regex=_getenv("MODIFIER_TOPIC_REGEX", r"(?i)^(camera settings|lighting)$"),
        no_repeat_last_n=_as_int(_getenv("NO_REPEAT_LAST_N", "20"), 20),

        # Subjects slots
        subjects_1_path=Path(_getenv("SUBJECTS_1_PATH", str(data_dir / "subjects_1.txt"))).resolve(),
        subjects_2_path=Path(_getenv("SUBJECTS_2_PATH", str(data_dir / "subjects_2.txt"))).resolve(),
        subjects_3_path=Path(_getenv("SUBJECTS_3_PATH", str(data_dir / "subjects_3.txt"))).resolve(),

        # LLM
        llm_mode=_getenv("LLM_MODE", "none").strip().lower(),
        llm_base_url=_getenv("LLM_BASE_URL", "").strip(),
        llm_api_key=_getenv("LLM_API_KEY", "").strip(),
        llm_model=_getenv("LLM_MODEL", "").strip(),

        animagine_rating=_getenv("ANIMAGINE_RATING", "").strip(),
    )

    if cfg.tg_send_as not in {"document", "photo"}:
        raise RuntimeError("TG_SEND_AS must be 'document' or 'photo'")

    if cfg.watermark_mode not in {"off", "fast", "strict"}:
        raise RuntimeError("WATERMARK_MODE must be 'off', 'fast' or 'strict'")

    return cfg
