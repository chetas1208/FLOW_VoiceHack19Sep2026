"""Pure-CLI capture fallback: /usr/sbin/screencapture. Main display only, no window title.

The file must exist for screencapture to write into it, so it lives in a private 0700 directory,
is pre-created 0600, is read straight into memory and unlinked in ``finally``.
"""

from __future__ import annotations

import os
import shutil
import tempfile

from .errors import CaptureFailed
from .imageinfo import image_size
from .runner import Runner, run

SCREENCAPTURE = "/usr/sbin/screencapture"
SIPS = "/usr/bin/sips"
_SUFFIX = {"jpeg": "jpg", "png": "png"}


def capture_main_display(image_format: str, max_dim: int, timeout: float, runner: Runner = run,
                         display_index: int = 1) -> tuple[bytes, int, int]:
    suffix = _SUFFIX.get(image_format)
    if suffix is None:
        raise CaptureFailed(f"unsupported image format {image_format!r}")
    directory = tempfile.mkdtemp(prefix="flow-capture-")  # mode 0700
    path = os.path.join(directory, f"frame.{suffix}")
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        result = runner([SCREENCAPTURE, "-x", "-t", suffix, "-D", str(display_index), path], timeout)
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()[:200]
            raise CaptureFailed(f"screencapture failed (exit {result.returncode}) {detail}".strip())
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise CaptureFailed("screencapture produced no image")
        os.chmod(path, 0o600)
        # Best-effort downscale in place; a failure keeps the original full-size image.
        try:
            runner([SIPS, "-Z", str(max_dim), path], timeout)
        except Exception:
            pass
        with open(path, "rb") as handle:
            data = handle.read()
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        shutil.rmtree(directory, ignore_errors=True)
    size = image_size(data)
    if size is None:
        raise CaptureFailed("screencapture output is not a valid PNG/JPEG image")
    return data, size[0], size[1]
