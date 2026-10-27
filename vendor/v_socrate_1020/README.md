# Vendored V-Socrate-1020 runtime

This directory contains the minimal inference runtime copied from:

`/apdcephfs_gy5/share_303098609/hunyuan/jaypernzhou/dev/Videoagent/V-Socrate-1020`

The source directory is treated as read-only. Benchmark data, model weights, caches,
results, and reproduction scripts are intentionally not copied.

Application-only changes in this copy:

- package-relative imports avoid colliding with `ai-train/models.py`;
- the Selector and Reflector accept open-ended exercise-form questions;
- preprocessing can use a content-hash cache key for temporary uploads.

V-Socrate still requires a local CLIP checkpoint and an OpenAI-compatible multimodal
vLLM endpoint with native tool calling. Configure those through the variables documented
in the project `.env.example`.
