from __future__ import annotations

import asyncio
import os

from app.config import load_config
from app.image_gen.sd_generator import SDGenerator
from app.pipeline import PostingPipeline
from app.prompt_bank.prompt_bank import PromptBank
from app.prompt_bank.topic_selector import TopicSelector
from app.prompt_expander.expander import PromptExpander
from app.prompt_expander.llm_adapter import LLMAdapter, LLMConfig
from app.publisher.publisher import Publisher
from app.scheduler.scheduler import SchedulerService
from app.storage.db import DB
from app.storage.migrations import run_migrations
from app.telegram_bot.bot import create_bot, create_dispatcher
from app.telegram_bot.handlers import create_admin_router


async def main() -> None:
    cfg = load_config()

    # Respect HF cache location
    os.environ["HF_HOME"] = str(cfg.hf_home)

    # Ensure dirs
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.hf_home.mkdir(parents=True, exist_ok=True)

    # DB
    run_migrations(str(cfg.db_path))
    db = DB(cfg.db_path)

    # Dynamic settings overrides (persist across restarts)
    paused_db = (db.get_setting("paused") or "").strip().lower()
    paused = paused_db in {"1", "true", "yes", "y"} if paused_db else cfg.paused

    interval_db = db.get_setting("post_interval_min")
    interval = int(interval_db) if (interval_db and interval_db.isdigit()) else cfg.post_interval_min

    model_id = db.get_setting("model_id") or cfg.model_id

    # Prompt bank
    bank = PromptBank(db=db, prompts_path=cfg.prompts_path)
    bank.reload()

    selector = TopicSelector(
        bank=bank,
        modifier_topic_regex=cfg.modifier_topic_regex,
        mode_a_weight=cfg.prompt_mode_a_weight,
    )

    llm = LLMAdapter(LLMConfig(mode=cfg.llm_mode, base_url=cfg.llm_base_url, api_key=cfg.llm_api_key, model=cfg.llm_model))
    expander = PromptExpander(
        subjects_1=cfg.subjects_1_path,
        subjects_2=cfg.subjects_2_path,
        subjects_3=cfg.subjects_3_path,
        negative_default=cfg.negative_default,
        llm=llm,
        animagine_rating=cfg.animagine_rating,
    )

    # SD generator
    generator = SDGenerator(
        model_id=model_id,
        hf_home=cfg.hf_home,
        output_dir=cfg.output_dir,
        dtype=cfg.dtype,
        sampler=cfg.sampler,
        device="cuda",
        enable_xformers=True,
        attention_slicing=False,
    )

    # Telegram
    bot = create_bot(cfg.bot_token)
    dp = create_dispatcher()

    publisher = Publisher(bot=bot, channel_id=cfg.channel_id, send_as=cfg.tg_send_as)

    pipeline = PostingPipeline(
        cfg=cfg,
        db=db,
        bank=bank,
        selector=selector,
        expander=expander,
        generator=generator,
        publisher=publisher,
    )

    async def job() -> None:
        res = await pipeline.run_once(forced=False)
        print("PIPELINE:", res.status, res.reason)

    scheduler = SchedulerService(job_coro=job, interval_min=interval, paused=paused)
    scheduler.start()

    # Admin commands
    dp.include_router(
        create_admin_router(
            admin_ids=cfg.admin_ids,
            db=db,
            bank=bank,
            scheduler=scheduler,
            pipeline=pipeline,
            generator=generator,
        )
    )

    print("OK: bot + scheduler started")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        generator.unload()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
