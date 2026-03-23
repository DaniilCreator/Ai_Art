from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.prompt_bank.prompt_bank import PromptBank
from app.storage.db import DB
from app.scheduler.scheduler import SchedulerService
from app.pipeline import PostingPipeline
from app.image_gen.sd_generator import SDGenerator

TZ_LOCAL = ZoneInfo("Europe/Bucharest")


def create_admin_router(
    *,
    admin_ids: set[int],
    db: DB,
    bank: PromptBank,
    scheduler: SchedulerService,
    pipeline: PostingPipeline,
    generator: SDGenerator,
) -> Router:
    router = Router()

    def is_admin(msg: Message) -> bool:
        uid = msg.from_user.id if msg.from_user else 0
        return uid in admin_ids

    def _parse_dt_any(v):
        """v может быть datetime или ISO-строка или None. Возвращает aware datetime UTC или None."""
        if not v:
            return None
        if isinstance(v, datetime):
            dt = v
        elif isinstance(v, str):
            try:
                dt = datetime.fromisoformat(v)
            except Exception:
                return None
        else:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _fmt_eta(seconds: int) -> str:
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return f"{h}ч {m}м" if h else f"{m}м {s}с"

    def _bar(pct: float, width: int = 20) -> str:
        pct = max(0.0, min(1.0, float(pct)))
        filled = int(pct * width)
        return "█" * filled + "░" * (width - filled)

    @router.message(Command("status"))
    async def cmd_status(message: Message):
        if not is_admin(message):
            return

        st = scheduler.status()
        counts = db.count_generated_statuses()
        errs = db.get_last_errors(limit=5)

        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(TZ_LOCAL)

        next_run_utc = _parse_dt_any(getattr(st, "next_run_at", None))
        next_local_str = "-"
        eta_str = "-"

        if next_run_utc:
            next_local = next_run_utc.astimezone(TZ_LOCAL)
            next_local_str = next_local.strftime("%Y-%m-%d %H:%M:%S %Z")
            eta_str = _fmt_eta(int((next_local - now_local).total_seconds()))

        # progress bar
        with generator._progress_lock:
            pr = dict(generator.progress)

        gen_line = "gen: <b>idle</b>"
        if pr.get("running") and int(pr.get("steps") or 0) > 0:
            step = int(pr.get("step") or 0)
            steps = int(pr.get("steps") or 1)
            pct = step / steps if steps else 0.0
            gen_line = f"gen: <b>{_bar(pct)}</b> <b>{int(pct * 100)}%</b> ({step}/{steps})"

        lines = [
            "<b>Состояние</b>",
            f"paused: <b>{getattr(st, 'paused', False)}</b>",
            f"interval: <b>{getattr(st, 'interval_min', '?')}</b> мин",
            f"now: <b>{now_local.strftime('%Y-%m-%d %H:%M:%S %Z')}</b>",
            f"next_run: <b>{next_local_str}</b>",
            f"eta: <b>{eta_str}</b>",
            gen_line,
            f"counts: {counts}",
        ]

        if errs:
            lines.append("\n<b>Последние ошибки/отклонения:</b>")
            for i, status, msg in errs:
                lines.append(f"#{i} {status}: {msg}")

        await message.answer("\n".join(lines))

    @router.message(Command("reload_prompts"))
    async def cmd_reload_prompts(message: Message):
        if not is_admin(message):
            return
        n = bank.reload()
        await message.answer(f"OK: загружено {n} промтов из JSON")

    @router.message(Command("post_now"))
    async def cmd_post_now(message: Message):
        if not is_admin(message):
            return
        res = await pipeline.run_once(forced=True)
        await message.answer(f"RESULT: {res.status} {res.reason or ''}")

    @router.message(Command("pause"))
    async def cmd_pause(message: Message):
        if not is_admin(message):
            return
        scheduler.pause()
        db.set_setting("paused", "true")
        await message.answer("OK: автопостинг на паузе")

    @router.message(Command("resume"))
    async def cmd_resume(message: Message):
        if not is_admin(message):
            return
        scheduler.resume()
        db.set_setting("paused", "false")
        await message.answer("OK: автопостинг возобновлён")

    @router.message(Command("set_interval"))
    async def cmd_set_interval(message: Message):
        if not is_admin(message):
            return
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer("Использование: /set_interval [minutes]")
            return
        minutes = max(1, int(parts[1]))
        scheduler.set_interval(minutes)
        db.set_setting("post_interval_min", str(minutes))
        await message.answer(f"OK: interval = {minutes} мин")

    @router.message(Command("set_model"))
    async def cmd_set_model(message: Message):
        if not is_admin(message):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.answer("Использование: /set_model [hf_model_id_or_path]")
            return
        model_id = parts[1].strip()
        db.set_setting("model_id", model_id)
        generator.set_model(model_id)
        await message.answer(f"OK: model_id = {model_id}")

    @router.message(Command("help"))
    async def cmd_help(message: Message):
        if not is_admin(message):
            return
        await message.answer(
            "Команды:\n"
            "/status\n"
            "/post_now\n"
            "/pause /resume\n"
            "/set_interval [min]\n"
            "/set_model [hf_model_id_or_path]\n"
            "/reload_prompts\n"
        )

    return router
