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
    revision: str | None = None  # pinned Hugging Face commit; remote code is only trusted at this revision


MODEL_REGISTRY = {
    # ``vision`` is retained as the stable storage key for existing installs;
    # its product role is now the Qwen intelligence model. Moondream remains a
    # legacy adapter and is never installed by the default model command.
    "vision": ModelSpec("vision", "Qwen3-VL 4B Instruct", "4b", "Qwen/Qwen3-VL-4B-Instruct", "Apache-2.0", "mlx-vlm/transformers", 7000, "local visual intelligence",
                    None),
    "voice": ModelSpec("voice", "Kokoro-82M", "82m", "hexgrad/Kokoro-82M", "Apache-2.0", "kokoro", 1000, "voice coaching",
                  "f3ff3571791e39611d31c381e3a41a3af07b4987"),
}

MODEL_VARIANTS = {
    "4b": MODEL_REGISTRY["vision"],
    "2b": ModelSpec("vision", "Qwen3-VL 2B Instruct", "2b", "Qwen/Qwen3-VL-2B-Instruct", "Apache-2.0",
                     "mlx-vlm/transformers", 4500, "local visual intelligence", None),
}

MODEL_ALIASES = {"intelligence": "vision"}


def model_dir() -> Path:
    return Path(os.getenv("FLOW_MODEL_DIR", str(config_dir() / "models"))).expanduser()


class ModelManager:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or model_dir()).expanduser()

    def path(self, key: str) -> Path:
        key = MODEL_ALIASES.get(key, key)
        if key not in MODEL_REGISTRY:
            raise ValueError(f"unknown model: {key}")
        return self.root / key

    @staticmethod
    def _spec(key: str, variant: str | None = None) -> ModelSpec:
        key = MODEL_ALIASES.get(key, key)
        if key == "vision" and variant:
            try:
                return MODEL_VARIANTS[variant]
            except KeyError as exc:
                raise ValueError(f"unknown intelligence variant: {variant}") from exc
        return MODEL_REGISTRY[key]

    def status(self, key: str | None = None, variant: str | None = None) -> list[dict[str, Any]]:
        key = MODEL_ALIASES.get(key, key) if key else key
        specs = [self._spec(key, variant)] if key else list(MODEL_REGISTRY.values())
        result = []
        for initial_spec in specs:
            spec = initial_spec
            path = self.path(spec.key)
            marker = path / "flow-model.json"
            state = "missing"
            manifest: dict[str, Any] = {}
            if key in (None, "vision") and spec.key == "vision" and variant is None and marker.is_file():
                try:
                    candidate_manifest = json.loads(marker.read_text())
                    spec = next((item for item in MODEL_VARIANTS.values()
                                 if item.source == candidate_manifest.get("source")), spec)
                except (OSError, json.JSONDecodeError):
                    pass
            if marker.is_file():
                try:
                    manifest = json.loads(marker.read_text())
                    payload = [item for item in path.rglob("*") if item.is_file() and item.name != marker.name]
                    valid_hash = True
                    if manifest.get("sha256"):
                        valid_hash = self._digest(payload, path) == manifest["sha256"]
                    state = "ready" if manifest.get("source") == spec.source and payload and valid_hash else "corrupt"
                except (OSError, json.JSONDecodeError):
                    state = "corrupt"
            result.append({**asdict(spec), "path": str(path), "status": state,
                           "manifest": manifest})
        return result

    @staticmethod
    def _digest(files: list[Path], root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(files):
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def install(self, key: str | None = None, variant: str | None = None) -> list[dict[str, Any]]:
        key = MODEL_ALIASES.get(key, key) if key else key
        keys = [key] if key else list(MODEL_REGISTRY)
        installed = []
        for item in keys:
            spec = self._spec(item, variant if item == "vision" else None)
            target = self.path(item)
            if self.status(item, variant if item == "vision" else None)[0]["status"] == "ready":
                installed.append(self.status(item, variant if item == "vision" else None)[0]); continue
            self.root.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{item}-", dir=self.root))
            try:
                try:
                    from huggingface_hub import snapshot_download
                except ImportError as exc:
                    raise RuntimeError("install model downloads with: pip install huggingface_hub") from exc
                snapshot_download(repo_id=spec.source, revision=spec.revision, local_dir=str(staging))
                files = [path for path in staging.rglob("*") if path.is_file()]
                if not files:
                    raise RuntimeError(f"model download produced no files: {spec.name}")
                digest = self._digest(files, staging)
                (staging / "flow-model.json").write_text(json.dumps({"key": item, "name": spec.name,
                    "version": spec.version, "source": spec.source, "revision": spec.revision, "license": spec.license,
                    "sha256": digest}, indent=2))
                if target.exists():
                    shutil.rmtree(target)
                staging.replace(target)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            installed.append(self.status(item, variant if item == "vision" else None)[0])
        return installed

    def remove(self, key: str) -> None:
        key = MODEL_ALIASES.get(key, key)
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
        try:
            free_mb = int(shutil.disk_usage(self.root).free / 1024 / 1024)
        except OSError:
            free_mb = None
        try:
            import mlx  # noqa: F401
            mlx_available = platform.system() == "Darwin" and platform.machine() == "arm64"
        except ImportError:
            mlx_available = False
        return {"platform": platform.platform(), "architecture": platform.machine(),
                "python": platform.python_version(), "memory_mb": memory_mb,
                "disk_free_mb": free_mb,
                "mlx_available": mlx_available,
                "qwen4b_compatible": bool((memory_mb is None or memory_mb >= 8_000)
                                            and (free_mb is None or free_mb >= MODEL_REGISTRY["vision"].memory_estimate_mb))}
