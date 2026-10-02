"""Local vision-language model: Qwen3-VL-8B-Instruct (Apache-2.0) in 4-bit NF4 (~6-7 GB VRAM), in refkit's venv.

One base model serves two jobs, loaded once per refkit process:
  ask()       the plain instruct model — the local critic (`refkit critique`), view-consistency checks
  editscore() EditScore's Qwen3-VL-8B LoRA switched on — scores an edit from (source, instruction, result)
The LoRA was trained on the bf16 base; on the NF4 base its scores are for ranking candidates, not absolute.
ComfyUI is asked to free its VRAM first (gpu.free_vram) — the card holds one engine at a time.
Weights: <engine>\\models\\vlm\\Qwen3-VL-8B-Instruct, <engine>\\models\\scoring\\EditScore-Qwen3-VL-8B-Instruct.
"""
from __future__ import annotations

from PIL import Image

from . import gpu, host
from .common import MODELS, RefkitError, log

BASE = MODELS / "vlm" / "Qwen3-VL-8B-Instruct"
EDITSCORE_LORA = MODELS / "scoring" / "EditScore-Qwen3-VL-8B-Instruct"
MAX_SIDE = 1024   # images are downsized to this long side before encoding (VRAM and speed)

_model = None
_processor = None
_has_lora = False


def load():
    global _model, _processor, _has_lora
    if _model is not None:
        return _model, _processor
    if not host.CUDA:
        raise RefkitError("refkit: the local VLM (Qwen3-VL in 4-bit bitsandbytes) needs an NVIDIA GPU")
    if not (BASE / "config.json").exists():
        raise RefkitError(f"refkit: local VLM not installed ({BASE}); run the setup screen's step 5 (local AI stack)")
    import torch
    from transformers import AutoProcessor, BitsAndBytesConfig, Qwen3VLForConditionalGeneration
    gpu.free_vram()
    log("loading Qwen3-VL-8B (4-bit)…")
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                               bnb_4bit_use_double_quant=True)
    model = Qwen3VLForConditionalGeneration.from_pretrained(BASE, quantization_config=quant, device_map="cuda:0",
                                                            dtype=torch.bfloat16)
    if (EDITSCORE_LORA / "adapter_config.json").exists():
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, EDITSCORE_LORA)   # kept separate: disabled for plain questions
        _has_lora = True
    _model, _processor = model.eval(), AutoProcessor.from_pretrained(BASE)
    return _model, _processor


def unload() -> None:
    global _model, _processor
    if _model is not None:
        import torch
        _model = _processor = None
        torch.cuda.empty_cache()


def _image(im) -> Image.Image:
    im = (Image.open(im) if not isinstance(im, Image.Image) else im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (128, 128, 128, 255))   # cutouts on mid grey, not black
        bg.alpha_composite(im)
        im = bg
    im = im.convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    return im


def generate(images: list, prompt: str, max_new_tokens: int = 384, temperature: float = 0.0, lora: bool = False,
             seed: int = 0) -> str:
    import torch
    model, proc = load()
    content = [{"type": "image", "image": _image(i)} for i in images] + [{"type": "text", "text": prompt}]
    inputs = proc.apply_chat_template([{"role": "user", "content": content}], tokenize=True,
                                      add_generation_prompt=True, return_dict=True, return_tensors="pt").to("cuda:0")
    kw = {"max_new_tokens": max_new_tokens, "do_sample": temperature > 0}
    if temperature > 0:
        torch.manual_seed(seed)
        kw.update(temperature=temperature, top_p=0.9, top_k=20)
    with torch.no_grad():
        if _has_lora and not lora:
            with model.disable_adapter():
                out = model.generate(**inputs, **kw)
        else:
            out = model.generate(**inputs, **kw)
    text = proc.batch_decode(out[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)[0]
    return text.strip()


def ask(images: list, prompt: str, max_new_tokens: int = 384) -> str:
    """Plain Qwen3-VL answer (deterministic)."""
    return generate(images, prompt, max_new_tokens=max_new_tokens)


class _EditScoreBackend:
    """EditScore's model interface (prepare_input / inference) on top of our shared 4-bit base + LoRA."""

    def prepare_input(self, images, text_prompt: str = ""):
        return (images if isinstance(images, list) else [images], text_prompt)

    def inference(self, prepared, seed=None):
        images, prompt = prepared
        return generate(images, prompt, max_new_tokens=512, temperature=0.7, lora=True, seed=seed or 0)


def editscore():
    """An editscore.EditScore evaluator wired to the shared model: .evaluate([source, result], instruction)."""
    from editscore import EditScore, vie_prompts
    load()
    if not _has_lora:
        raise RefkitError(f"refkit: EditScore LoRA not installed ({EDITSCORE_LORA})")
    ev = EditScore.__new__(EditScore)   # skip its own (bf16, ~17 GB) model loading
    ev.backbone, ev.score_range, ev.reduction, ev.seed, ev.num_pass = "qwen3vl", 25, "average_last", 42, 1
    ev.model = _EditScoreBackend()
    ev.context = vie_prompts._context_no_delimit_reasoning_first
    ev.SC_prompt = "\n".join([ev.context, vie_prompts._prompts_0shot_two_image_edit_rule,
                              vie_prompts._prompts_0shot_tie_rule_SC.replace("10", str(ev.score_range))])
    ev.PQ_prompt = "\n".join([ev.context, vie_prompts._prompts_0shot_rule_PQ.replace("10", str(ev.score_range))])
    return ev
