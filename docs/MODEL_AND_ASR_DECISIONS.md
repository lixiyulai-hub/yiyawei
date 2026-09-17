# Model and ASR Decisions

Date: 2026-06-02

## ASR

v0.1 now uses FunASR Paraformer as the only product ASR path.

Decision:

- Keep `paraformer-zh` through FunASR for Chinese-first spoken input.
- Do not keep ASR comparison UI in the default software.
- Do not keep SenseVoice, Whisper fallback, or phonetic correction dictionaries in the main path.
- If CUDA is unavailable, use the same Paraformer model on CPU as a device fallback.

The product should stay lightweight: one ASR model, then LLM semantic harness.

## LLM

Main model:

- `qwen3.5:9b`, or a similar 9B general-purpose Chinese-capable model.

Fast model:

- `gemma4:e4b`.

Do not use Qwen3 as the default recommendation. Do not use coder-specific models as the default because this product is for language cleanup and prompt compilation, not code generation.

## Install Readiness

Before pulling models, make sure Ollama is installed, available in `PATH`, and
configured with a model directory appropriate for the user's machine. If a
custom cache location is needed, set it in the user's environment rather than
hard-coding a local path in the project.
