"""Retriever factory: TAKA_RETRIEVER=clip | blip (configs/common_env.sh).

The retriever is used everywhere CLIP used to be: VideoIndex frame embeddings and scene
split (preprocessing), Search (text query over the 1-fps embeddings, focus and cover
modes) and Similar (image query; frames outside the 1-fps index are encoded on the fly).
Caches are kept apart per retriever:
$TAKA_CACHE_ROOT/<retriever>/<dataset>/.
"""
import os

RETRIEVERS = ("clip", "blip")
EMBED_DIMS = {"clip": 512, "blip": 256}    # ViT-B/32 projection / BLIP ITC projection


def retriever_name() -> str:
    name = os.environ["TAKA_RETRIEVER"].strip().lower()   # validated by config_check
    if name not in RETRIEVERS:
        raise SystemExit(f"[config error] TAKA_RETRIEVER={name!r}; allowed: {', '.join(RETRIEVERS)}")
    return name


def load_retriever():
    name = retriever_name()
    if name == "blip":
        from .blip_retrieval import BLIPTool
        tool = BLIPTool(enable_caption=False)
        print(f"  Retriever  : BLIP-large ITM (LAVIS, model_large_retrieval_coco.pth) @ {tool.device}")
    else:
        from .clip import CLIPTool
        tool = CLIPTool(model_name=os.environ["CLIP_MODEL_NAME"], enable_caption=False)
        print(f"  Retriever  : CLIP {os.environ['CLIP_MODEL_NAME']} @ {tool.device}")
    tool.retriever_name = name
    tool.embed_dim = EMBED_DIMS[name]
    return tool


def cache_dir_for(dataset: str) -> str:
    return os.path.join(os.environ["TAKA_CACHE_ROOT"], retriever_name(), dataset)
