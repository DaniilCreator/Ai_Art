from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

LOCAL_TZ = ZoneInfo("Europe/Bucharest")

UTC = timezone.utc


@dataclass
class SchedulerStatus:
    paused: bool
    interval_min: int
    next_run_at: str | None


class SchedulerService:
    """Internal scheduler for autoposting.

    Uses APScheduler AsyncIOScheduler under the hood.
    """

    def __init__(self, job_coro: Callable[[], Awaitable[None]],
                 interval_min: int,
                 paused: bool = False):
        self.job_coro = job_coro
        self.interval_min = max(1, int(interval_min))
        self.paused = bool(paused)

        self._scheduler = AsyncIOScheduler(timezone=str(UTC))
        self._job_id = "autopost"
        self._lock = asyncio.Lock()

    def start(self) -> None:
        if self._scheduler.running:
            return

        # запоминаем loop, в котором запущен бот (он есть!)
        self._loop = asyncio.get_running_loop()

        # сначала добавляем job, потом стартуем scheduler
        self._add_or_replace_job()
        self._scheduler.start()

        if self.paused:
            self._scheduler.pause_job(self._job_id)

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def _add_or_replace_job(self) -> None:
        trigger = IntervalTrigger(minutes=self.interval_min)

        def _kick():
            # этот код запускается в потоке APScheduler -> нужен thread-safe вызов
            fut = asyncio.run_coroutine_threadsafe(self._safe_run(), self._loop)

            # чтобы исключения не терялись:
            def _done_cb(f):
                try:
                    f.result()
                except Exception as e:
                    # если у тебя есть логгер — пиши туда
                    print("Scheduler tick error:", repr(e))

            fut.add_done_callback(_done_cb)

        self._scheduler.add_job(
            _kick,
            trigger=trigger,
            id=self._job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )

    async def _safe_run(self) -> None:
        # Prevent concurrent /post_now and scheduled tick
        async with self._lock:
            await self.job_coro()

    async def trigger_now(self) -> None:
        async with self._lock:
            await self.job_coro()

    def set_interval(self, minutes: int) -> None:
        self.interval_min = max(1, int(minutes))
        if self._scheduler.running:
            self._add_or_replace_job()
            if self.paused:
                self._scheduler.pause_job(self._job_id)

    def pause(self) -> None:
        self.paused = True
        if self._scheduler.running:
            self._scheduler.pause_job(self._job_id)

    def resume(self) -> None:
        self.paused = False
        if self._scheduler.running:
            self._scheduler.resume_job(self._job_id)
            job = self._scheduler.get_job(self._job_id)
            if job:
                job.modify(next_run_time=datetime.now(LOCAL_TZ) + timedelta(minutes=self.interval_min))

    def status(self) -> SchedulerStatus:
        next_run = None
        try:
            job = self._scheduler.get_job(self._job_id)
            if job and job.next_run_time:
                next_run = job.next_run_time.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            next_run = None

        return SchedulerStatus(
            paused=self.paused,
            interval_min=self.interval_min,
            next_run_at=next_run,
        )
