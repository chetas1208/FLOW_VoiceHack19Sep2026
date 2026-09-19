# Local model manager

FLOW has exactly two registered default local model artifacts:

* Qwen3-VL 4B Instruct (`Qwen/Qwen3-VL-4B-Instruct`) for local intelligence.
* Kokoro-82M (`hexgrad/Kokoro-82M`) for local speech.

The `vision` storage key is retained for backward compatibility with existing
installations; use `flow models install intelligence` for the product command.
The legacy Moondream adapter remains optional and is not installed by default.

`ModelManager` stores them under `FLOW_MODEL_DIR`, or the FLOW configuration
directory's `models/` folder. Downloads use a staging directory and an atomic
rename; a manifest marker is written only after files exist. `flow models
status`, `install`, and `remove` operate on `vision`, `voice`, or both.

The model manager does not silently install fallback models. Apple Silicon/MLX
availability is reported by `flow doctor`/model status, while the current
Moondream adapter uses the optional Transformers runtime. Actual model download,
memory use, inference latency, and Kokoro playback require a host with the
optional dependencies and sufficient hardware.
