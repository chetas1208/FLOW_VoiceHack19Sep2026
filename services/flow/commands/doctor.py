"""Portable FLOW health report."""

from __future__ import annotations

import platform

NAME = "doctor"


def add_parser(subparsers) -> None:
    subparsers.add_parser(NAME, help="show local observer, model, voice, and storage readiness")


def run(args) -> int:
    from ..config import config_dir, data_dir
    from ..models_registry import ModelManager
    from ..voice.kokoro import KokoroVoiceEngine

    models = {item["key"]: item for item in ModelManager().status()}
    observer = "ready" if platform.system() == "Darwin" else "not_configured (ScreenCaptureKit requires macOS)"
    voice = KokoroVoiceEngine().status()
    print("FLOW DOCTOR\n")
    print(f"Platform      {platform.platform()}")
    print(f"Observer      {observer}")
    print(f"Vision        {models['vision']['status']} ({models['vision']['path']})")
    print(f"Voice         {models['voice']['status']} ({voice.get('model_path') or models['voice']['path']})")
    print(f"Data          {'ready' if data_dir().parent.exists() else 'not_ready'} ({data_dir()})")
    print(f"Config        {config_dir()}")
    return 0
