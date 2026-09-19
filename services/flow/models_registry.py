"""The only two model artifacts FLOW installs for the local coach."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import config_dir


@dataclass(frozen=True, slots=True)
class ModelSpec:
    key: str
    name: str
    version: str
    source: str
    license: str
    runtime: str
    memory_estimate_mb: int
    purpose: str


MODEL_REGISTRY = {
    "vision": ModelSpec("vision", "Moondream 2B", "2b", "vikhyatk/moondream2", "Apache-2.0", "transformers", 5000, "desktop understanding"),
    "voice": ModelSpec("voice", "Kokoro-82M", "82m", "hexgrad/Kokoro-82M", "Apache-2.0", "kokoro", 1000, "voice coaching"),
}


def model_dir() -> Path:
    return Path(os.getenv("FLOW_MODEL_DIR", str(config_dir() / "models"))).expanduser()


class ModelManager:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or model_dir()).expanduser()

    def path(self, key: str) -> Path:
        if key not in MODEL_REGISTRY:
            raise ValueError(f"unknown model: {key}")
        return self.root / key

    def status(self, key: str | None = None) -> list[dict[str, Any]]:
        specs = [MODEL_REGISTRY[key]] if key else list(MODEL_REGISTRY.values())
        result = []
        for spec in specs:
            path = self.path(spec.key)
            marker = path / "flow-model.json"
            state = "missing"
            manifest: dict[str, Any] = {}
            if marker.is_file():
                try:
                    manifest = json.loads(marker.read_text())
                    state = "ready" if manifest.get("source") == spec.source and any(path.iterdir()) else "corrupt"
                except (OSError, json.JSONDecodeError):
                    state = "corrupt"
            result.append({**asdict(spec), "path": str(path), "status": state,
                           "manifest": manifest})
        return result

    def install(self, key: str | None = None) -> list[dict[str, Any]]:
        keys = [key] if key else list(MODEL_REGISTRY)
        installed = []
        for item in keys:
            spec = MODEL_REGISTRY[item]
            target = self.path(item)
            if self.status(item)[0]["status"] == "ready":
                installed.append(self.status(item)[0]); continue
            self.root.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{item}-", dir=self.root))
            try:
                try:
                    from huggingface_hub import snapshot_download
                except ImportError as exc:
                    raise RuntimeError("install model downloads with: pip install huggingface_hub") from exc
                snapshot_download(repo_id=spec.source, local_dir=str(staging), local_dir_use_symlinks=False)
                files = [path for path in staging.rglob("*") if path.is_file()]
                if not files:
                    raise RuntimeError(f"model download produced no files: {spec.name}")
                digest = hashlib.sha256()
                for path in sorted(files):
                    digest.update(str(path.relative_to(staging)).encode()); digest.update(path.read_bytes())
                (staging / "flow-model.json").write_text(json.dumps({"key": item, "name": spec.name,
                    "version": spec.version, "source": spec.source, "license": spec.license,
                    "sha256": digest.hexdigest()}, indent=2))
                if target.exists():
                    shutil.rmtree(target)
                staging.replace(target)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            installed.append(self.status(item)[0])
        return installed

    def remove(self, key: str) -> None:
        target = self.path(key)
        if target.exists():
            shutil.rmtree(target)

    def hardware(self) -> dict[str, Any]:
        memory_mb = None
        try:
            import psutil
            memory_mb = int(psutil.virtual_memory().total / 1024 / 1024)
        except ImportError:
            pass
        return {"platform": platform.platform(), "architecture": platform.machine(),
                "python": platform.python_version(), "memory_mb": memory_mb,
                "mlx_available": platform.system() == "Darwin" and platform.machine() == "arm64"}
