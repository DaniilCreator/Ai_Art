from __future__ import annotations
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import AppConfig, pick_resolution
from app.image_filter.watermark_fast import detect_text_like_regions
from app.image_filter.watermark_strict import ocr_and_check
from app.image_gen.sd_generator import GenParams, SDGenerator
from app.prompt_bank.prompt_bank import PromptBank
from app.prompt_bank.topic_selector import TopicSelector
from app.prompt_expander.expander import PromptExpander
from app.publisher.publisher import Publisher
from app.storage.db import DB

UTC = timezone.utc


@dataclass(frozen=True)
class PipelineResult:
    status: str  # posted|generated|rejected|error
    gen_id: int | None
    file_path: str | None
    reason: str | None


class PostingPipeline:
    """Generate (or reuse) an image and publish it to the channel.

    Rules:
    - Pipeline init is external (SDGenerator.load()) but generator is reused.
    - Watermark/text filter rejects images; we do NOT attempt to remove watermarks.
    - Avoid duplicates by sha256 unique in DB.
    - On restart, tries to post pending generated images before generating new ones.
    """

    def __init__(
        self,
        cfg: AppConfig,
        db: DB,
        bank: PromptBank,
        selector: TopicSelector,
        expander: PromptExpander,
        generator: SDGenerator,
        publisher: Publisher,
    ):
        self.cfg = cfg
        self.db = db
        self.bank = bank
        self.selector = selector
        self.expander = expander
        self.generator = generator
        self.publisher = publisher
        self._run_lock = asyncio.Lock()

    async def run_once(self, forced: bool = False) -> PipelineResult:
        # --- Anti-parallel: do not allow two runs at the same time ---
        # If already running, do not wait; just skip (prevents scheduler + /post_now overlap)
        if getattr(self, "_run_lock", None) is not None and self._run_lock.locked():
            return PipelineResult(status="rejected", gen_id=None, file_path=None, reason="busy")

        async with self._run_lock:
            # 1) post pending first (unless forced generate)
            if not forced:
                pending = self.db.get_oldest_pending_generated()
                if pending:
                    return await self._publish_existing(pending)

            # 2) generate new
            avoid = self.db.get_recent_prompt_ids(self.cfg.no_repeat_last_n)
            selected = self.selector.select(self.cfg.prompt_mode, avoid_prompt_ids=avoid)
            expanded = self.expander.expand(selected)

            width, height = pick_resolution(self.cfg)

            params = GenParams(
                width=width,
                height=height,
                steps=self.cfg.steps,
                guidance_scale=self.cfg.cfg,
                sampler=self.cfg.sampler,
                seed=self.cfg.seed,
            )

            # filename
            file_stem = f"{time.time_ns()}_{selected.mode.lower()}_{selected.primary.topic.replace(' ', '_')[:16]}"

            # heavy generation: run in thread to not block event loop
            try:
                path, sha256, seconds = await asyncio.to_thread(
                    self.generator.generate_and_save,
                    prompt=expanded.prompt_text,
                    negative_prompt=expanded.negative_prompt,
                    params=params,
                    file_stem=file_stem,
                )
            except Exception as e:
                return PipelineResult(status="error", gen_id=None, file_path=None, reason=f"gen_error:{e}")

            # duplicates
            if self.db.sha256_exists(sha256):
                try:
                    Path(path).unlink(missing_ok=True)
                except Exception:
                    pass
                return PipelineResult(status="rejected", gen_id=None, file_path=None, reason="duplicate_sha256")

            created_at = datetime.now(UTC).isoformat()
            gen_id = self.db.insert_generated(
                prompt_ids=json.dumps(expanded.prompt_ids, ensure_ascii=False),
                prompt_text=expanded.prompt_text,
                negative_prompt=expanded.negative_prompt,
                # Store the effective model id (it can be changed at runtime via /set_model)
                model_id=self.generator.model_id,
                params_json=json.dumps(params.__dict__, ensure_ascii=False),
                file_path=str(path),
                status="generated",
                created_at=created_at,
                sha256=sha256,
            )

            # mark prompts used as soon as image is generated (even if rejected)
            self.db.mark_prompts_used(expanded.prompt_ids)

            # 3) filter
            if self.cfg.reject_if_text_likely and self.cfg.watermark_mode != "off":
                fast = detect_text_like_regions(path)
                if not fast.ok:
                    self.db.update_generated_status(
                        gen_id,
                        status="rejected",
                        reject_reason=f"fast:{fast.reason}:{fast.score:.3f}",
                    )
                    return PipelineResult(status="rejected", gen_id=gen_id, file_path=str(path),
                                          reason=f"fast:{fast.reason}")

                if self.cfg.watermark_mode == "strict":
                    strict = await asyncio.to_thread(ocr_and_check, path)
                    if not strict.ok:
                        self.db.update_generated_status(gen_id, status="rejected", reject_reason=f"ocr:{strict.reason}")
                        return PipelineResult(status="rejected", gen_id=gen_id, file_path=str(path),
                                              reason=f"ocr:{strict.reason}")

            # 4) publish
            return await self._publish_by_id(gen_id)

    async def _publish_existing(self, row) -> PipelineResult:
        gen_id = int(row["id"])
        file_path = row["file_path"]
        if not Path(file_path).exists():
            self.db.update_generated_status(gen_id, status="error", error_text="file_missing")
            return PipelineResult(status="error", gen_id=gen_id, file_path=file_path, reason="file_missing")
        return await self._publish_by_id(gen_id)

    async def _publish_by_id(self, gen_id: int) -> PipelineResult:
        row = None
        # fetch row
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM generated_images WHERE id=?", (gen_id,)).fetchone()
        if row is None:
            return PipelineResult(status="error", gen_id=gen_id, file_path=None, reason="db_row_missing")

        file_path = str(row["file_path"])

        caption = self._build_caption()
        res = await self.publisher.publish(file_path=file_path, caption=caption)
        if not res.ok:
            self.db.update_generated_status(gen_id, status="error", error_text=res.error)
            return PipelineResult(status="error", gen_id=gen_id, file_path=file_path, reason=res.error)

        posted_at = datetime.now(UTC).isoformat()
        self.db.update_generated_status(gen_id, status="posted", posted_at=posted_at)
        return PipelineResult(status="posted", gen_id=gen_id, file_path=file_path, reason=None)

    def _build_caption(self) -> str:
        tpl = (self.cfg.caption_template or "").strip()
        if not tpl:
            return ""
        # Supported placeholders are intentionally minimal
        return tpl
