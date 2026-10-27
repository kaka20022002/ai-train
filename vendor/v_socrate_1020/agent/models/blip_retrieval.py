"""BLIP-large ITM retriever: drop-in replacement for CLIPTool's retrieval interface.

Implements the methods the selection pipeline calls on its retriever:
  - extract_frame_features(frames) -> torch.Tensor (N, 256), L2-normalized
  - encode_text(text) -> np.ndarray (256,), L2-normalized

Both live in BLIP's ITC projection space (vision_proj / text_proj, 256-d, aligned), so
image and text embeddings are dot-product comparable, exactly like CLIP's in VideoIndex
(scene split, Search, Similar).

Model: LAVIS "blip_image_text_matching" / "large" = model_large_retrieval_coco.pth, the same
checkpoint the official AKS and FOCUS implementations use. LAVIS looks for it under
$TORCH_HOME/hub/checkpoints/ and needs bert-base-uncased in $HF_HOME (offline).
Ported from TAKA0527/models/blip_retrieval.py (2026-07-15); device rule = CLIPTool's.
"""

import os
import threading

import numpy as np
import torch
from PIL import Image

EMBED_DIM = 256


class BLIPTool:
    def __init__(self, model_type: str = "large", enable_caption: bool = False):
        from lavis.models import load_model_and_preprocess

        if os.environ["CLIP_FORCE_CPU"].strip().lower() in ("1", "true", "yes", "on"):
            self.device = "cpu"
        else:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model, self.vis_processors, self.txt_processors = load_model_and_preprocess(
            "blip_image_text_matching", model_type, device=self.device, is_eval=True
        )
        self.model.eval()
        self._gpu_lock = threading.Lock()
        self.enable_caption = False

    @staticmethod
    def _to_pil(image):
        if isinstance(image, Image.Image):
            return image.convert("RGB")
        arr = np.asarray(image)
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
        if arr.shape[2] > 3:
            arr = arr[:, :, :3]
        return Image.fromarray(arr).convert("RGB")

    def extract_frame_features(self, frames):
        """frames: list of PIL/np images -> L2-normalized ITC image features (N, 256)."""
        if not frames:
            raise ValueError("No frames provided for BLIP image preprocessing.")
        proc = self.vis_processors["eval"]
        batch = torch.stack([proc(self._to_pil(f)) for f in frames]).to(self.device)
        with self._gpu_lock, torch.no_grad():
            img_embeds = self.model.visual_encoder.forward_features(batch)   # (N, L, H)
            feats = self.model.vision_proj(img_embeds[:, 0, :])             # (N, 256)
        return torch.nn.functional.normalize(feats, dim=-1).float()

    def query_too_long(self, text: str):
        """Reason a query exceeds the BLIP text processor's word limit (None if it fits).
        LAVIS would cut extra words silently; Search returns this as a tool error instead."""
        max_words = getattr(self.txt_processors["eval"], "max_words", None)
        n = len(str(text).split())
        if max_words and n > max_words:
            return f"{n} words, the BLIP text processor takes at most {max_words}"
        return None

    def encode_text(self, text: str) -> np.ndarray:
        """text -> L2-normalized ITC text feature (256,)."""
        txt = self.txt_processors["eval"](text)
        tok = self.model.tokenizer(txt, return_tensors="pt").to(self.device)
        with self._gpu_lock, torch.no_grad():
            out = self.model.text_encoder(tok.input_ids, attention_mask=tok.attention_mask, mode="text")
            feat = self.model.text_proj(out.last_hidden_state[:, 0, :])     # (1, 256)
        return torch.nn.functional.normalize(feat, dim=-1).float().cpu().numpy().flatten()

    def encode_texts(self, texts) -> np.ndarray:
        return np.stack([self.encode_text(t) for t in texts], axis=0)

    def compute_similarity(self, feat1, feat2):
        f1 = torch.as_tensor(feat1).flatten().float()
        f2 = torch.as_tensor(feat2).flatten().float()
        return torch.dot(f1, f2).item()
