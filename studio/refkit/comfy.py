"""Minimal ComfyUI API client: find (or start) our local server, queue an API-format workflow, collect outputs.

Finding the server: REFKIT_COMFY_URL wins; otherwise ports 8188-8195 are probed and only a ComfyUI whose argv points
in our engine folder (ATELIER_ENGINE) is used. That lets refkit share the server Comfy Desktop starts for the same install instead
of launching a second process on the same 16 GB card. If none is running, a headless one is started.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import time
import uuid
from pathlib import Path

import requests

from .common import STUDIO, STUDIO_ROOT, RefkitError, log

WORKFLOWS = STUDIO / "workflows"
COMFY_DIR = STUDIO_ROOT / "ComfyUI"
PORTS = range(8188, 8196)
_url: str | None = None


def _stats(base: str) -> dict | None:
    try:
        r = requests.get(f"{base}/system_stats", timeout=2)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def _ours(stats: dict) -> bool:
    """Our install: the `comfy` shim runs a relative ComfyUI\\main.py but always passes engine-folder paths
    (--extra-model-paths-config / --output-directory); Comfy Desktop's record uses the absolute main.py path."""
    argv = " ".join(stats.get("system", {}).get("argv", [])).lower().replace("/", "\\")
    return str(STUDIO_ROOT).lower() + "\\" in argv


def find() -> str | None:
    """URL of our running ComfyUI, or None. Cached once found."""
    global _url
    if _url and _stats(_url):
        return _url
    env = os.environ.get("REFKIT_COMFY_URL")
    if env:
        _url = env.rstrip("/")
        return _url if _stats(_url) else None
    for port in PORTS:
        base = f"http://127.0.0.1:{port}"
        s = _stats(base)
        if s and _ours(s):
            _url = base
            return base
    return None


def url() -> str:
    base = find()
    if not base:
        raise RefkitError("refkit: ComfyUI is not running (call ensure_running first)")
    return base


def up() -> bool:
    return find() is not None


def _free_port() -> int:
    for port in PORTS:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RefkitError(f"refkit: no free port in {PORTS.start}-{PORTS.stop - 1} for ComfyUI")


def housekeeping(days: int = 14, log_mb: int = 50) -> None:
    """Rotate comfyui.log and prune refkit's own scratch in ComfyUI (content-hash uploads, outputs/refkit copies —
    every deliverable was already copied to its destination folder)."""
    logfile = STUDIO_ROOT / "comfyui.log"
    if logfile.exists() and logfile.stat().st_size > log_mb * 1_000_000:
        logfile.replace(logfile.with_suffix(".log.1"))
    cutoff = time.time() - days * 86400
    for folder, pattern in ((COMFY_DIR / "ComfyUI" / "input", "refkit-*"), (STUDIO_ROOT / "output" / "refkit", "**/*")):
        for f in folder.glob(pattern) if folder.exists() else []:
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass


def ensure_running(timeout: int = 180) -> str:
    global _url
    if up():
        return url()
    housekeeping()
    port = _free_port()
    log(f"starting ComfyUI (headless, local-only) on :{port}…")
    env = os.environ | {"PYTHONNOUSERSITE": "1"}
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    logf = open(STUDIO_ROOT / "comfyui.log", "ab")
    proc = subprocess.Popen([str(Path.home() / ".local" / "bin" / "comfy.cmd"), "--port", str(port)], env=env,
                            creationflags=flags, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    t = time.time()
    while time.time() - t < timeout:
        if _stats(base):
            _url = base
            return base
        if proc.poll() is not None:
            raise RefkitError(f"refkit: ComfyUI exited during startup (code {proc.returncode}); "
                              f"see {STUDIO_ROOT / 'comfyui.log'}")
        time.sleep(1)
    raise RefkitError(f"refkit: ComfyUI did not come up on {base}; see {STUDIO_ROOT / 'comfyui.log'}")


def upload(image: Path) -> str:
    """Upload under a content-hash name so concurrent runs (or Comfy Desktop) never overwrite each other's inputs."""
    data = Path(image).read_bytes()
    name = f"refkit-{hashlib.sha1(data).hexdigest()[:16]}{Path(image).suffix.lower() or '.png'}"
    try:
        r = requests.post(f"{url()}/upload/image", files={"image": (name, data)}, data={"overwrite": "true"}, timeout=60)
        r.raise_for_status()
    except requests.RequestException as e:
        raise RefkitError(f"refkit: upload to ComfyUI failed: {e}") from None
    return r.json()["name"]


def load_workflow(name: str) -> dict:
    return json.loads((WORKFLOWS / f"{name}.json").read_text(encoding="utf-8"))


def add_lora(wf: dict, lora_name: str, strength: float = 1.0) -> str:
    """Put a LoraLoaderModelOnly right after the (single) UNETLoader; everything that read the UNet reads the LoRA."""
    unets = [k for k, n in wf.items() if n["class_type"] == "UNETLoader"]
    if len(unets) != 1:
        raise RefkitError(f"refkit: expected one UNETLoader for the LoRA, found {len(unets)}")
    src, key = [unets[0], 0], f"lora_{sum(k.startswith('lora_') for k in wf)}"
    for n in wf.values():   # rewire every reader of the UNet first …
        for name, v in n["inputs"].items():
            if v == src:
                n["inputs"][name] = [key, 0]
    # … then add the LoRA, which alone still reads the UNet (a second call slots in between: UNet -> lora_1 -> lora_0)
    wf[key] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": src, "lora_name": lora_name,
                                                                "strength_model": strength}}
    return key


def prune(wf: dict) -> dict:
    """Drop every node no Save* output depends on (unused branches, sample inputs, UI previews). In place."""
    keep, stack = set(), [k for k, n in wf.items() if n["class_type"].startswith("Save")]
    while stack:
        cur = stack.pop()
        if cur in keep or cur not in wf:
            continue
        keep.add(cur)
        stack += [v[0] for v in wf[cur]["inputs"].values() if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)]
    for k in [k for k in wf if k not in keep]:
        del wf[k]
    return wf


SAMPLERS = ("KSampler", "KSamplerAdvanced", "SamplerCustom", "CFGGuider", "BasicGuider", "DualCFGGuider")
ATTENTION = os.environ.get("REFKIT_ATTENTION", "comfy kitchen attention")   # "pytorch attention" turns it off


def kitchen_attention(wf: dict) -> int:
    """Run a workflow's diffusion model(s) on Comfy Kitchen INT8 attention (faster) through one
    ModelAttentionBackend node per model feeding a sampler/guider. Per workflow rather than the global
    --use-ck-attention flag, so a workflow that misbehaves with it (ComfyUI issue #16027 reports TRELLIS.2 shape
    corruption on older builds; not reproduced on 0.38 here) can be left out, and REFKIT_ATTENTION="pytorch
    attention" turns it off everywhere. The node falls back to PyTorch attention where Comfy Kitchen is missing."""
    wrapped: dict[tuple, str] = {}
    for n in list(wf.values()):
        src = n["inputs"].get("model")
        if n["class_type"] not in SAMPLERS or not isinstance(src, list):
            continue
        key = wrapped.get(tuple(src))
        if key is None:
            key = wrapped[tuple(src)] = f"refkit_attn{len(wrapped)}"
            wf[key] = {"class_type": "ModelAttentionBackend", "inputs": {"model": src, "attention": ATTENTION}}
        n["inputs"]["model"] = [key, 0]
    return len(wrapped)


def patch(wf: dict, match, key: str, value, expect: int | None = 1) -> int:
    """Set inputs[key]=value on nodes where match(node) is true (match may be a class_type string).
    Fails loudly when the count differs from `expect` (None = at least one) — a renamed node after a ComfyUI
    update must not be silently ignored."""
    pred = (lambda n: n["class_type"] == match) if isinstance(match, str) else match
    hits = [n for n in wf.values() if pred(n)]
    if (expect is None and not hits) or (expect is not None and len(hits) != expect):
        raise RefkitError(f"refkit: workflow patch for {key!r} matched {len(hits)} node(s), expected "
                          f"{expect if expect is not None else '>=1'} — the workflow changed; re-export it")
    for n in hits:
        n["inputs"][key] = value
    return len(hits)


def validate(wf: dict) -> list[str]:
    """Unknown node classes / input names against the running server's /object_info."""
    info = requests.get(f"{url()}/object_info", timeout=60).json()
    problems = []
    for nid, n in wf.items():
        spec = info.get(n["class_type"])
        if spec is None:
            problems.append(f"node {nid}: unknown class {n['class_type']}")
            continue
        known = {**spec["input"].get("required", {}), **spec["input"].get("optional", {})}
        # Empty leftovers from the UI graph (e.g. SaveGLB's old `image: ""`) are ignored by ComfyUI; a *valued*
        # unknown input means our patch targets a renamed input.
        problems += [f"node {nid} {n['class_type']}: unknown input {k!r}" for k, v in n["inputs"].items()
                     if k not in known and "." not in k and v not in ("", None)]
    return problems


def _cancel(base: str, prompt_id: str) -> None:
    """Cancel one job, queued or running. The Jobs API (present in ComfyUI 0.38) does both in one idempotent
    call; older servers get the queue-delete + interrupt pair."""
    try:
        r = requests.post(f"{base}/api/jobs/{prompt_id}/cancel", timeout=5)
        if r.status_code == 404:
            requests.post(f"{base}/queue", json={"delete": [prompt_id]}, timeout=5)
            running = requests.get(f"{base}/queue", timeout=5).json().get("queue_running", [])
            if any(len(j) > 1 and j[1] == prompt_id for j in running):
                requests.post(f"{base}/interrupt", json={"prompt_id": prompt_id}, timeout=5)
        log("cancelled the ComfyUI job")
    except requests.RequestException:
        pass


def queue(wf: dict, timeout: int = 1800) -> list[dict]:
    """Submit and wait: the output file records of one workflow run."""
    return wait(submit(wf), timeout)


def submit(wf: dict) -> str:
    """Queue a workflow; returns its prompt_id. Partial validation failures count as failures."""
    base = url()
    try:
        r = requests.post(f"{base}/prompt", json={"prompt": wf, "client_id": uuid.uuid4().hex}, timeout=30)
    except requests.RequestException as e:
        raise RefkitError(f"refkit: could not reach ComfyUI at {base}: {e}") from None
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    # ComfyUI answers 200 and runs the valid part when only some outputs fail validation; treat that as failure.
    if not r.ok or body.get("node_errors"):
        detail = json.dumps(body.get("node_errors") or body.get("error") or r.text, indent=1)[:2500]
        if r.ok:
            _cancel(base, body.get("prompt_id", ""))
        raise RefkitError(f"refkit: ComfyUI rejected the workflow:\n{detail}")
    return body["prompt_id"]


def wait(prompt_id: str, timeout: int = 1800) -> list[dict]:
    base = url()
    t = time.time()
    try:
        while time.time() - t < timeout:
            try:
                h = requests.get(f"{base}/history/{prompt_id}", timeout=10).json().get(prompt_id)
            except requests.RequestException as e:
                raise RefkitError(f"refkit: lost connection to ComfyUI ({e}); was it closed?") from None
            if h:
                status = h.get("status", {})
                if status.get("status_str") == "error" or not status.get("completed", True):
                    msgs = [m for m in status.get("messages", []) if m[0] in ("execution_error", "execution_interrupted")]
                    raise RefkitError(f"refkit: ComfyUI job failed: {json.dumps(msgs)[:2500]}")
                return _outputs(h)
            time.sleep(1)
    except KeyboardInterrupt:
        _cancel(base, prompt_id)
        raise
    _cancel(base, prompt_id)
    raise RefkitError(f"refkit: ComfyUI job timed out after {timeout}s")


def _outputs(h: dict) -> list[dict]:
    files = []
    for node_out in h.get("outputs", {}).values():
        for key in ("images", "gifs", "video", "3d", "result", "mesh", "model_file"):
            for item in node_out.get(key, []) or []:
                if isinstance(item, dict) and "filename" in item:
                    files.append(item)
                elif isinstance(item, str):
                    files.append({"filename": item, "subfolder": "", "type": "output"})
    return files


def fetch(item: dict, dest: Path) -> Path:
    # Some savers (Save3DAdvanced) report "sub/dir/name.glb" as the filename with an empty subfolder.
    name = item["filename"].replace("\\", "/")
    sub = item.get("subfolder", "") or ""
    if "/" in name:
        head, name = name.rsplit("/", 1)
        sub = f"{sub}/{head}" if sub else head
    r = requests.get(f"{url()}/view", params={"filename": name, "subfolder": sub,
                                              "type": item.get("type", "output")}, timeout=300)
    r.raise_for_status()
    out = dest / Path(item["filename"]).name
    out.write_bytes(r.content)
    return out
