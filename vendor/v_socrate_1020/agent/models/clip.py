import os
import threading
from typing import Optional

import numpy as np
import torch
import torch.nn.functional as F
from transformers import CLIPModel, CLIPProcessor


class CLIPTool:
    """
    保留 CLIP 的向量检索能力，并在同一个工具类中懒加载 BLIP caption 模型。

    这样主流程无需替换检索接口，就能直接为场景生成 caption。

    线程安全：所有 GPU 推理操作通过 _gpu_lock 串行化，
    防止多线程并发推理导致显存竞争或 OOM。
    """

    def __init__(
        self,
        model_name: str = "openai/clip-vit-base-patch32",
        caption_model_name: str = "Salesforce/blip-image-captioning-base",
        caption_dtype: str = "fp32",
        enable_caption: bool = True,
        caption_max_new_tokens: int = 40,
        caption_batch_size: int = 4,
    ):
        # CLIP_FORCE_CPU=1 强制 CLIP 跑 CPU(显存被 vLLM/test.py 占满时用)。默认仍 cuda, 不改原行为。
        if os.environ["CLIP_FORCE_CPU"].strip().lower() in ("1", "true", "yes", "on"):
            self.device = "cpu"
        else:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.compute_dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.model = CLIPModel.from_pretrained(model_name).to(self.device)
        if self.device == "cuda":
            self.model = self.model.half()
        self.model.eval()
        self.processor = CLIPProcessor.from_pretrained(model_name)
        self._gpu_lock = threading.Lock()
        self._image_processor = self.processor.image_processor
        self._img_do_resize = bool(getattr(self._image_processor, "do_resize", True))
        self._img_size_cfg = getattr(self._image_processor, "size", {"shortest_edge": 224})
        self._img_do_center_crop = bool(getattr(self._image_processor, "do_center_crop", True))
        self._img_crop_cfg = getattr(self._image_processor, "crop_size", {"height": 224, "width": 224})
        self._img_do_rescale = bool(getattr(self._image_processor, "do_rescale", True))
        self._img_rescale_factor = float(getattr(self._image_processor, "rescale_factor", 1.0 / 255.0))
        self._img_do_normalize = bool(getattr(self._image_processor, "do_normalize", True))
        self._img_mean = torch.tensor(
            getattr(self._image_processor, "image_mean", [0.48145466, 0.4578275, 0.40821073]),
            dtype=torch.float32,
            device=self.device,
        ).view(1, 3, 1, 1)
        self._img_std = torch.tensor(
            getattr(self._image_processor, "image_std", [0.26862954, 0.26130258, 0.27577711]),
            dtype=torch.float32,
            device=self.device,
        ).view(1, 3, 1, 1)

        self.enable_caption = enable_caption
        self.caption_model_name = caption_model_name
        self.caption_local_files_only = os.path.exists(caption_model_name)
        self.caption_max_new_tokens = caption_max_new_tokens
        self.caption_batch_size = caption_batch_size
        self._caption_processor = None
        self._caption_model = None
        self._caption_dtype = self._resolve_caption_dtype(caption_dtype)

    def _to_rgb_numpy(self, image):
        if isinstance(image, np.ndarray):
            arr = image
        else:
            arr = np.asarray(image.convert("RGB"))
        if arr.ndim != 3:
            raise ValueError(f"Unexpected image shape: {arr.shape}")
        if arr.shape[2] == 1:
            arr = np.repeat(arr, 3, axis=2)
        if arr.shape[2] > 3:
            arr = arr[:, :, :3]
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        return arr

    @staticmethod
    def _normalize_size_cfg(size_cfg):
        if size_cfg is None:
            return None
        if isinstance(size_cfg, dict):
            return size_cfg
        if hasattr(size_cfg, "to_dict"):
            try:
                return size_cfg.to_dict()
            except Exception:
                pass
        if hasattr(size_cfg, "items"):
            try:
                return dict(size_cfg.items())
            except Exception:
                pass

        out = {}
        for key in ("shortest_edge", "height", "width"):
            if hasattr(size_cfg, key):
                value = getattr(size_cfg, key)
                if value is not None:
                    out[key] = value
        return out if out else size_cfg

    @staticmethod
    def _extract_hw(size_cfg, default_h=224, default_w=224):
        size_cfg = CLIPTool._normalize_size_cfg(size_cfg)
        if isinstance(size_cfg, dict):
            if "shortest_edge" in size_cfg:
                s = int(size_cfg["shortest_edge"])
                return s, s, True
            h = int(size_cfg.get("height", default_h))
            w = int(size_cfg.get("width", default_w))
            return h, w, False
        s = int(size_cfg)
        return s, s, True

    def _resize_like_clip(self, tensor_chw: torch.Tensor) -> torch.Tensor:
        h, w = int(tensor_chw.shape[-2]), int(tensor_chw.shape[-1])
        target_h, target_w, by_shortest = self._extract_hw(self._img_size_cfg)
        if by_shortest:
            shortest = max(1, min(h, w))
            scale = float(target_h) / float(shortest)
            new_h = max(1, int(round(h * scale)))
            new_w = max(1, int(round(w * scale)))
        else:
            new_h, new_w = target_h, target_w
        return F.interpolate(
            tensor_chw.unsqueeze(0),
            size=(new_h, new_w),
            mode="bicubic",
            align_corners=False,
            antialias=True,
        ).squeeze(0)

    def _center_crop_like_clip(self, tensor_chw: torch.Tensor) -> torch.Tensor:
        crop_h, crop_w, _ = self._extract_hw(self._img_crop_cfg)
        h, w = int(tensor_chw.shape[-2]), int(tensor_chw.shape[-1])

        pad_h = max(crop_h - h, 0)
        pad_w = max(crop_w - w, 0)
        if pad_h > 0 or pad_w > 0:
            top = pad_h // 2
            bottom = pad_h - top
            left = pad_w // 2
            right = pad_w - left
            tensor_chw = F.pad(tensor_chw, (left, right, top, bottom), mode="constant", value=0)
            h, w = int(tensor_chw.shape[-2]), int(tensor_chw.shape[-1])

        top = max((h - crop_h) // 2, 0)
        left = max((w - crop_w) // 2, 0)
        return tensor_chw[:, top: top + crop_h, left: left + crop_w]

    def _prepare_image_inputs(self, frames):
        pixel_values = []
        for frame in frames:
            arr = self._to_rgb_numpy(frame)
            tensor = torch.from_numpy(arr).to(self.device, non_blocking=True)
            tensor = tensor.permute(2, 0, 1).to(torch.float32)
            if self._img_do_resize:
                tensor = self._resize_like_clip(tensor)
            if self._img_do_center_crop:
                tensor = self._center_crop_like_clip(tensor)
            if self._img_do_rescale:
                tensor = tensor * self._img_rescale_factor
            if self._img_do_normalize:
                tensor = (tensor.unsqueeze(0) - self._img_mean) / self._img_std
                tensor = tensor.squeeze(0)
            pixel_values.append(tensor)
        if not pixel_values:
            raise ValueError("No frames provided for CLIP image preprocessing.")
        batch = torch.stack(pixel_values, dim=0).to(self.compute_dtype)
        return {"pixel_values": batch}

    def extract_frame_features(self, frames):
        inputs = self._prepare_image_inputs(frames)
        with self._gpu_lock, torch.no_grad():
            with torch.autocast(device_type="cuda", dtype=self.compute_dtype, enabled=self.device == "cuda"):
                features = self._ensure_tensor(self.model.get_image_features(**inputs))
        return features / features.norm(dim=-1, keepdim=True)

    def compute_similarity(self, feat1, feat2):
        return torch.dot(feat1, feat2).item()

    def compute_text_image_similarity(self, text, frames):
        text_inputs = self.processor(text=[text], return_tensors="pt", padding=True).to(self.device)
        image_inputs = self._prepare_image_inputs(frames)
        inputs = {**text_inputs, **image_inputs}
        with self._gpu_lock, torch.no_grad():
            with torch.autocast(device_type="cuda", dtype=self.compute_dtype, enabled=self.device == "cuda"):
                outputs = self.model(**inputs)
        logits_per_image = outputs.logits_per_image  # (num_frames, 1)
        return logits_per_image.squeeze(1).cpu().numpy()

    @staticmethod
    def _ensure_tensor(output) -> torch.Tensor:
        """将模型输出统一转为 Tensor（兼容不同 transformers 版本）。"""
        if isinstance(output, torch.Tensor):
            return output
        if hasattr(output, "pooler_output") and output.pooler_output is not None:
            return output.pooler_output
        if isinstance(output, (tuple, list)):
            return output[0]
        return output.last_hidden_state[:, 0]

    MAX_TEXT_TOKENS = 77

    def query_too_long(self, text: str) -> Optional[str]:
        """Reason a query does not fit CLIP's 77-token text window (None if it fits).
        Queries are never truncated silently: Search returns this as a tool error."""
        n = len(self.processor.tokenizer(text)["input_ids"])
        if n > self.MAX_TEXT_TOKENS:
            return f"{n} tokens, the {self.retriever_label} text encoder takes at most {self.MAX_TEXT_TOKENS}"
        return None

    retriever_label = "CLIP"

    def encode_text(self, text: str) -> np.ndarray:
        """Encode text to L2-normalized CLIP embedding (D,)."""
        inputs = self.processor(text=[text], return_tensors="pt", padding=True).to(self.device)
        with self._gpu_lock, torch.no_grad():
            with torch.autocast(device_type="cuda", dtype=self.compute_dtype, enabled=self.device == "cuda"):
                emb = self._ensure_tensor(self.model.get_text_features(**inputs))
        emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb.cpu().numpy().flatten()

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        """Batch encode texts to L2-normalized CLIP embeddings (N, D)."""
        inputs = self.processor(text=texts, return_tensors="pt", padding=True).to(self.device)
        with self._gpu_lock, torch.no_grad():
            with torch.autocast(device_type="cuda", dtype=self.compute_dtype, enabled=self.device == "cuda"):
                emb = self._ensure_tensor(self.model.get_text_features(**inputs))
        emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb.cpu().numpy()

    def _ensure_caption_model(self) -> None:
        if not self.enable_caption:
            raise RuntimeError("Caption generation is disabled for this CLIPTool.")
        if self._caption_model is not None and self._caption_processor is not None:
            return

        from transformers import BlipForConditionalGeneration, BlipProcessor

        self._caption_processor = BlipProcessor.from_pretrained(
            self.caption_model_name,
            local_files_only=self.caption_local_files_only,
        )
        self._caption_model = BlipForConditionalGeneration.from_pretrained(
            self.caption_model_name,
            torch_dtype=self._caption_dtype,
            local_files_only=self.caption_local_files_only,
        ).to(self.device)
        self._caption_model.eval()

    def _resolve_caption_dtype(self, caption_dtype: str) -> torch.dtype:
        dtype = (caption_dtype or "fp32").strip().lower()
        if dtype not in {"fp16", "fp32"}:
            dtype = "fp32"
        if dtype == "fp16" and self.device != "cuda":
            print("[BLIP] fp16 requested on CPU; fallback to fp32.")
            return torch.float32
        return torch.float16 if dtype == "fp16" else torch.float32

    def _fallback_caption_to_fp32(self, reason: str) -> None:
        if self._caption_dtype != torch.float16:
            raise RuntimeError(reason)
        print(f"[BLIP] {reason}; retry with fp32.")
        self._caption_dtype = torch.float32
        self._caption_model = None
        self._caption_processor = None
        self._ensure_caption_model()

    @staticmethod
    def _is_dtype_mismatch_error(err: Exception) -> bool:
        msg = str(err).lower()
        return (
            "expected scalar type half but found float" in msg
            or "expected scalar type float but found half" in msg
            or "mat1 and mat2 must have the same dtype" in msg
        )

    def _move_caption_inputs(self, inputs):
        moved = {}
        for key, value in inputs.items():
            if torch.is_tensor(value):
                if torch.is_floating_point(value):
                    moved[key] = value.to(self.device, dtype=self._caption_dtype)
                else:
                    moved[key] = value.to(self.device)
            else:
                moved[key] = value
        return moved

    def caption(self, image) -> str:
        self._ensure_caption_model()
        try:
            inputs = self._caption_processor(images=image, return_tensors="pt")
            inputs = self._move_caption_inputs(inputs)
            with self._gpu_lock, torch.no_grad():
                ids = self._caption_model.generate(
                    **inputs,
                    max_new_tokens=self.caption_max_new_tokens,
                )
        except RuntimeError as e:
            if not self._is_dtype_mismatch_error(e):
                raise
            self._fallback_caption_to_fp32(str(e))
            inputs = self._caption_processor(images=image, return_tensors="pt")
            inputs = self._move_caption_inputs(inputs)
            with self._gpu_lock, torch.no_grad():
                ids = self._caption_model.generate(
                    **inputs,
                    max_new_tokens=self.caption_max_new_tokens,
                )
        return self._caption_processor.batch_decode(ids, skip_special_tokens=True)[0].strip()

    def caption_batch(self, images):
        self._ensure_caption_model()
        results = []
        for i in range(0, len(images), self.caption_batch_size):
            batch = images[i : i + self.caption_batch_size]
            try:
                inputs = self._caption_processor(images=batch, return_tensors="pt", padding=True)
                inputs = self._move_caption_inputs(inputs)
                with self._gpu_lock, torch.no_grad():
                    ids = self._caption_model.generate(
                        **inputs,
                        max_new_tokens=self.caption_max_new_tokens,
                    )
            except RuntimeError as e:
                if not self._is_dtype_mismatch_error(e):
                    raise
                self._fallback_caption_to_fp32(str(e))
                inputs = self._caption_processor(images=batch, return_tensors="pt", padding=True)
                inputs = self._move_caption_inputs(inputs)
                with self._gpu_lock, torch.no_grad():
                    ids = self._caption_model.generate(
                        **inputs,
                        max_new_tokens=self.caption_max_new_tokens,
                    )
            texts = self._caption_processor.batch_decode(ids, skip_special_tokens=True)
            results.extend(text.strip() for text in texts)
        return results

    # ── Entity 提取（BLIP conditional generation）──────────────

    @staticmethod
    def _parse_entities(raw: str) -> list[str]:
        """从 BLIP 条件生成的输出中解析 entity 列表。"""
        import re
        raw = raw.strip().rstrip(".")
        # 按逗号、"and"、"&" 分割
        parts = re.split(r",\s*|\s+and\s+|\s*&\s*", raw)
        entities = []
        for p in parts:
            p = p.strip().lstrip("a ").lstrip("an ").lstrip("the ")
            p = p.strip()
            if p and len(p) > 1:
                entities.append(p)
        # 去重保序
        seen = set()
        unique = []
        for e in entities:
            if e.lower() not in seen:
                seen.add(e.lower())
                unique.append(e)
        return unique

    def _conditional_generate(self, image, text_prompt: str) -> str:
        """用 BLIP 的条件生成模式（text prompt + image）生成文本。"""
        self._ensure_caption_model()
        try:
            inputs = self._caption_processor(
                images=image, text=text_prompt, return_tensors="pt"
            )
            inputs = self._move_caption_inputs(inputs)
            with self._gpu_lock, torch.no_grad():
                ids = self._caption_model.generate(
                    **inputs, max_new_tokens=self.caption_max_new_tokens,
                )
        except RuntimeError as e:
            if not self._is_dtype_mismatch_error(e):
                raise
            self._fallback_caption_to_fp32(str(e))
            inputs = self._caption_processor(
                images=image, text=text_prompt, return_tensors="pt"
            )
            inputs = self._move_caption_inputs(inputs)
            with self._gpu_lock, torch.no_grad():
                ids = self._caption_model.generate(
                    **inputs, max_new_tokens=self.caption_max_new_tokens,
                )
        return self._caption_processor.batch_decode(ids, skip_special_tokens=True)[0].strip()

    def caption_with_entities(self, image) -> tuple[str, list[str]]:
        """
        为单张图像生成 caption 和 entity 列表。

        Returns:
            (caption, entities) — caption 是自由文本描述，
            entities 是从条件生成中解析出的物体/实体清单。
        """
        cap = self.caption(image)
        raw_entities = self._conditional_generate(
            image, "the main objects in this image are"
        )
        entities = self._parse_entities(raw_entities)
        return cap, entities

    def caption_with_entities_batch(
        self, images: list,
    ) -> list[tuple[str, list[str]]]:
        """批量生成 caption + entities。"""
        captions = self.caption_batch(images)
        results = []
        for img, cap in zip(images, captions):
            raw_entities = self._conditional_generate(
                img, "the main objects in this image are"
            )
            entities = self._parse_entities(raw_entities)
            results.append((cap, entities))
        return results
