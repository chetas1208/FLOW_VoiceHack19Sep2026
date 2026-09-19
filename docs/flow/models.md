# Local model manager

FLOW has exactly two registered local model artifacts:

* Moondream 2B (`vikhyatk/moondream2`) for visual perception.
* Kokoro-82M (`hexgrad/Kokoro-82M`) for local speech.

`ModelManager` stores them under `FLOW_MODEL_DIR`, or the FLOW configuration
directory's `models/` folder. Downloads use a staging directory and an atomic
rename; a manifest marker is written only after files exist. `flow models
status`, `install`, and `remove` operate on `vision`, `voice`, or both.

The model manager does not silently install fallback models. Apple Silicon/MLX
availability is reported by `flow doctor`/model status, while the current
Moondream adapter uses the optional Transformers runtime. Actual model download,
memory use, inference latency, and Kokoro playback require a host with the
optional dependencies and sufficient hardware.
