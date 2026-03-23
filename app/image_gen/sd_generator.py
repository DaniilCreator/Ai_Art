from __future__ import annotations

import hashlib
import os
import time
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import torch
from PIL import Image


@dataclass(frozen=True)
class GenParams:
    width: int
    height: int
    steps: int
    guidance_scale: float
    sampler: str
    seed: Optional[int]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _torch_dtype(dtype: str) -> torch.dtype:
    d = (dtype or "").lower().strip()
    if d in {"float16", "fp16", "half"}:
        return torch.float16
    if d in {"bfloat16", "bf16"}:
        return torch.bfloat16
    return torch.float32


def _build_scheduler(pipe, name: str):
    from diffusers import (
        EulerAncestralDiscreteScheduler,
        EulerDiscreteScheduler,
        DPMSolverMultistepScheduler,
        DDIMScheduler,
    )

    n = (name or "").lower().strip()
    if n in {"euler_a", "euler-ancestral"}:
        return EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
    if n in {"euler"}:
        return EulerDiscreteScheduler.from_config(pipe.scheduler.config)
    if n in {"dpmpp_2m", "dpmpp", "dpm"}:
        return DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
    if n in {"ddim"}:
        return DDIMScheduler.from_config(pipe.scheduler.config)
    return pipe.scheduler


class SDGenerator:
    def __init__(
        self,
        model_id: str,
        hf_home: str | Path,
        output_dir: str | Path,
        dtype: str = "float16",
        sampler: str = "euler_a",
        device: str = "cuda",
        enable_xformers: bool = True,
        attention_slicing: bool = False,
    ):
        self.model_id = model_id
        self.hf_home = str(hf_home)
        self.output_dir = Path(output_dir)
        self.dtype = dtype
        self.sampler = sampler
        self.device = device
        self.enable_xformers = enable_xformers
        self.attention_slicing = attention_slicing

        self._gen_lock = threading.Lock()
        self._pipe = None

        self._progress_lock = threading.Lock()
        self.progress = {
            "running": False,
            "step": 0,
            "steps": 0,
            "started_at_utc": None,
        }

    def set_model(self, model_id: str) -> None:
        model_id = (model_id or "").strip()
        if model_id and model_id != self.model_id:
            self.model_id = model_id
            self._pipe = None
            self._free_cuda()

    def unload(self) -> None:
        self._pipe = None
        self._free_cuda()

    @staticmethod
    def _free_cuda() -> None:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def load(self) -> None:
        if self._pipe is not None:
            return

        os.environ.setdefault("HF_HOME", self.hf_home)
        os.environ.setdefault("TRANSFORMERS_CACHE", self.hf_home)

        from diffusers import DiffusionPipeline

        pipe = DiffusionPipeline.from_pretrained(
            self.model_id,
            torch_dtype=_torch_dtype(self.dtype),
            use_safetensors=True,
            safety_checker=None,
            requires_safety_checker=False,
        )

        pipe.scheduler = _build_scheduler(pipe, self.sampler)

        if self.device == "cuda" and torch.cuda.is_available():
            pipe = pipe.to("cuda")
            pipe.set_progress_bar_config(disable=False)

            if self.enable_xformers:
                try:
                    pipe.enable_xformers_memory_efficient_attention()
                except Exception:
                    pass

            if self.attention_slicing:
                try:
                    pipe.enable_attention_slicing()
                except Exception:
                    pass
        else:
            pipe = pipe.to("cpu")

        self._pipe = pipe

    @property
    def pipe(self):
        if self._pipe is None:
            raise RuntimeError("Pipeline not loaded. Call SDGenerator.load() once at startup.")
        return self._pipe

    def generate_and_save(
        self,
        prompt: str,
        negative_prompt: str,
        params: GenParams,
        file_stem: str,
    ) -> Tuple[Path, str, float]:
        self.load()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        generator = None
        if params.seed is not None:
            generator = torch.Generator(
                device=self.device if torch.cuda.is_available() else "cpu"
            ).manual_seed(params.seed)

        t0 = time.perf_counter()

        with self._progress_lock:
            self.progress["running"] = True
            self.progress["step"] = 0
            self.progress["steps"] = int(params.steps)
            self.progress["started_at_utc"] = datetime.now(timezone.utc)

        def _cb(step: int, timestep: int, latents):
            with self._progress_lock:
                self.progress["step"] = int(step) + 1

        try:
            with self._gen_lock:
                out = self.pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt if negative_prompt else None,
                    num_inference_steps=int(params.steps),
                    guidance_scale=float(params.guidance_scale),
                    height=int(params.height),
                    width=int(params.width),
                    generator=generator,
                    callback=_cb,
                    callback_steps=1,
                )
        finally:
            with self._progress_lock:
                self.progress["running"] = False

        img: Image.Image = out.images[0]
        if img.mode != "RGB":
            img = img.convert("RGB")

        path = self.output_dir / f"{file_stem}.png"
        img.save(path, format="PNG", compress_level=1)  # быстрее чем optimize=True

        sha256 = _sha256_file(path)
        seconds = time.perf_counter() - t0
        return path, sha256, seconds
