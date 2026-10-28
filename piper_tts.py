"""Piper local text-to-speech provider tool."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


def _default_model() -> str:
    return os.getenv("PIPER_DEFAULT_MODEL", "en_US-lessac-medium").strip() or "en_US-lessac-medium"


def _data_dir() -> Path | None:
    raw = os.getenv("PIPER_DATA_DIR", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


class PiperTTS(BaseTool):
    name = "piper_tts"
    version = "0.1.1"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "piper"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["cmd:piper"]
    install_instructions = (
        "Install Piper TTS:\n"
        "  pip install piper-tts\n"
        "Or download from https://github.com/rhasspy/piper/releases\n"
        "Then download a voice model, e.g.:\n"
        "  python -m piper.download_voices en_US-lessac-medium --data-dir D:\\piper-voices\n"
        "Set PIPER_DATA_DIR in .env to that folder (optional PIPER_DEFAULT_MODEL)."
    )
    agent_skills = ["text-to-speech"]

    capabilities = [
        "text_to_speech",
        "offline_generation",
    ]
    supports = {
        "voice_cloning": False,
        "multilingual": False,
        "offline": True,
        "native_audio": True,
    }
    best_for = [
        "offline narration fallback",
        "privacy-sensitive local-only workflows",
    ]
    not_good_for = [
        "best-in-class expressive voice quality",
        "voice clone matching",
    ]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
            "model": {
                "type": "string",
                "default": "en_US-lessac-medium",
                "description": "Voice id (e.g. en_US-lessac-medium) or path to a .onnx file",
            },
            "speaker_id": {
                "type": "integer",
                "default": 0,
            },
            "length_scale": {
                "type": "number",
                "default": 1.0,
            },
            "sentence_silence": {
                "type": "number",
                "default": 0.3,
            },
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=512, vram_mb=0, disk_mb=200, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=[])
    idempotency_key_fields = ["text", "model", "speaker_id", "length_scale"]
    side_effects = ["writes audio file to output_path"]
    user_visible_verification = ["Listen to generated audio for intelligibility"]

    def get_status(self) -> ToolStatus:
        if shutil.which("piper"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if self.get_status() != ToolStatus.AVAILABLE:
            return ToolResult(
                success=False,
                error="Piper TTS not available. " + self.install_instructions,
            )

        start = time.time()
        try:
            result = self._generate(inputs)
        except Exception as exc:
            return ToolResult(success=False, error=f"Local TTS generation failed: {exc}")

        result.duration_seconds = round(time.time() - start, 2)
        return result

    def _resolve_model(self, model: str, data_dir: Path | None) -> str:
        """Return CLI --model argument: path to .onnx when possible, else voice id."""
        model = (model or _default_model()).strip()
        p = Path(model)
        if p.suffix.lower() == ".onnx" and p.exists():
            return str(p.resolve())
        if p.exists() and p.is_file():
            return str(p.resolve())

        if data_dir is not None:
            # bare id → <data_dir>/<id>.onnx
            stem = model
            if stem.lower().endswith(".onnx"):
                stem = stem[: -len(".onnx")]
            candidate = data_dir / f"{stem}.onnx"
            if candidate.exists():
                return str(candidate.resolve())

        return model

    def _generate(self, inputs: dict[str, Any]) -> ToolResult:
        output_path = Path(inputs.get("output_path", "tts_output.wav"))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        model_in = inputs.get("model") or _default_model()
        data_dir = _data_dir()
        model_arg = self._resolve_model(str(model_in), data_dir)

        cmd: list[str] = ["piper"]
        if data_dir is not None:
            data_dir.mkdir(parents=True, exist_ok=True)
            cmd.extend(["--data-dir", str(data_dir.resolve())])

        cmd.extend(
            [
                "--model",
                model_arg,
                "--speaker",
                str(inputs.get("speaker_id", 0)),
                "--length-scale",
                str(inputs.get("length_scale", 1.0)),
                "--sentence-silence",
                str(inputs.get("sentence_silence", 0.3)),
                "--output_file",
                str(output_path),
            ]
        )

        proc = subprocess.run(
            cmd,
            input=inputs["text"],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if proc.returncode != 0:
            return ToolResult(
                success=False,
                error=f"Piper failed (exit {proc.returncode}): {proc.stderr}",
            )
        if not output_path.exists():
            return ToolResult(
                success=False,
                error=f"Piper output file missing: {output_path}",
            )

        resolved_label = str(model_in)
        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "model": resolved_label,
                "model_resolved": model_arg,
                "data_dir": str(data_dir) if data_dir else None,
                "speaker_id": inputs.get("speaker_id", 0),
                "text_length": len(inputs["text"]),
                "output": str(output_path),
                "format": "wav",
            },
            artifacts=[str(output_path)],
            model=resolved_label,
        )