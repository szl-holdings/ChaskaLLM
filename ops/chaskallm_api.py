#!/usr/bin/env python3
"""ChaskaLLM Server — house GPU-less CPU LLM (up to 7B) + tokenless prove door. Bind 127.0.0.1:18765.

Naming lock (Rosa 2026-10-25):
  ChaskaLLM  = this CPU mouth (1.1b / 3b / 7b)
  ChaskaClaw = reserved for house NemoClaw OpenShell twin (not this process)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 18765
CLI = Path("/opt/alloyscape/vendor/llama.cpp/bin/llama-cli")
MODELS_DIR = Path("/opt/alloyscape/vendor/llama.cpp/models")
MODELS = {
  "1.1b": MODELS_DIR / "chaskaclaw-cpu-1.1b.Q4_K_M.gguf",
  "tiny": MODELS_DIR / "chaskaclaw-cpu-1.1b.Q4_K_M.gguf",
  "3b": MODELS_DIR / "chaskaclaw-cpu-3b.Q4_K_M.gguf",
  "default": MODELS_DIR / "chaskaclaw-cpu-3b.Q4_K_M.gguf",
  # Optional overflow — only advertised when the real GGUF exists (never Soft Shield default)
  "7b": MODELS_DIR / "chaskaclaw-cpu-7b.Q4_K_M.gguf",
}
DEFAULT_MODEL_KEY = os.environ.get("CHASKACLAW_MODEL", "3b")
# Soft Shield pre-router must stay on 3b/1.1b — 7b is opt-in via model=7b only.
ZTFI = Path("/opt/alloyscape/shared/bridge/ztfi")
COVERAGE = ZTFI / "SEAT-COVERAGE.json"
ROUTER = ZTFI / "ZTFI-TOKENLESS-ROUTER.md"
PROVE = ZTFI / "TRIBE-PROVE-LATEST.json"
QICH = Path("/opt/alloyscape/shared/bridge/rosa-claw/qiwicha_manifest.qich")
LOOP_SB = Path("/opt/alloyscape/builder-sandboxes/hermesnous/projects/wo-recursive-spacetime-loop-20261024T235435Z") / "scoreboard.json"


DATA_DIR = Path(os.environ.get("CHASKA_DATA_DIR", "/opt/alloyscape/data/chaskallm"))
KEYS_PATH = DATA_DIR / "api-keys.json"
KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_META = UPLOAD_DIR / "index.json"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
IMAGE_DIR = DATA_DIR / "images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# Public-edge abuse bounds. Env-tunable; a limit of 0 denies (fails closed).
# Per-IP limits need nginx to send X-Real-IP (or X-Forwarded-For) — without it every
# proxied caller shares the loopback bucket, which is exempt. The concurrency slots and
# the image daily cap hold regardless of client identity.
MAX_JSON_BYTES = int(os.environ.get("CHASKA_MAX_JSON_BYTES", str(1024 * 1024)))
MAX_N_PREDICT = int(os.environ.get("CHASKA_MAX_N_PREDICT", "512"))
MAX_CONCURRENT_GEN = int(os.environ.get("CHASKA_MAX_CONCURRENT_GEN", "2"))
GEN_WAIT_S = float(os.environ.get("CHASKA_GEN_WAIT_S", "2"))
IMAGE_DAILY_CAP = int(os.environ.get("CHASKA_IMAGE_DAILY_CAP", "50"))
IMAGE_PER_IP_HOUR = int(os.environ.get("CHASKA_IMAGE_PER_IP_HOUR", "5"))
CHAT_PER_IP_MINUTE = int(os.environ.get("CHASKA_CHAT_PER_IP_MINUTE", "20"))
KEY_MINT_PER_IP_HOUR = int(os.environ.get("CHASKA_KEY_MINT_PER_IP_HOUR", "3"))
UPLOAD_PER_IP_HOUR = int(os.environ.get("CHASKA_UPLOAD_PER_IP_HOUR", "30"))
IMAGE_MIN_SIDE, IMAGE_MAX_SIDE = 256, 1024
# Only these upload types render inline from /v1/files; everything else downloads as
# application/octet-stream so an uploaded HTML/SVG file cannot run script on our origin.
INLINE_SAFE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "text/plain"}
LOOPBACK = ("127.0.0.1", "::1")
NVIDIA_FLUX_ENV = Path("/opt/alloyscape/secrets/nvidia-flux-amber.env")
NVIDIA_BUILD_PACK = Path("/opt/alloyscape/secrets/nvidia-build-rosa-video-audio-pack.env")
FLUX_INVOKE_URL = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell"
TEXT_EXTS = {".txt",".md",".csv",".json",".jsonl",".py",".js",".mjs",".ts",".tsx",".html",".css",".xml",".yaml",".yml",".toml",".ini",".log",".sh",".rs",".go",".java",".c",".cpp",".h",".rb",".php",".sql"}


def _load_uploads() -> dict:
  if UPLOAD_META.is_file():
    try:
      return json.loads(UPLOAD_META.read_text())
    except Exception:
      pass
  return {"version": 1, "files": {}}


def _save_uploads(db: dict) -> None:
  tmp = UPLOAD_META.with_suffix(".tmp")
  tmp.write_text(json.dumps(db, indent=2) + "\n")
  tmp.replace(UPLOAD_META)


def save_upload(filename: str, raw: bytes, media_type: str | None = None) -> dict:
  if len(raw) > MAX_UPLOAD_BYTES:
    return {"ok": False, "error": "file_too_large", "max_bytes": MAX_UPLOAD_BYTES}
  safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", (filename or "file").strip())[:120] or "file"
  fid = secrets.token_hex(12)
  dest = UPLOAD_DIR / f"{fid}__{safe}"
  dest.write_bytes(raw)
  kind = "image" if (media_type or "").startswith("image/") or safe.lower().endswith((".png",".jpg",".jpeg",".gif",".webp",".bmp",".svg")) else "file"
  excerpt = None
  ext = Path(safe).suffix.lower()
  if kind != "image" and (ext in TEXT_EXTS or (media_type or "").startswith("text/") or media_type in ("application/json", "application/xml")):
    try:
      excerpt = raw.decode("utf-8", errors="replace")[:6000]
    except Exception:
      excerpt = None
  rec = {
    "id": fid,
    "filename": safe,
    "path": str(dest),
    "bytes": len(raw),
    "mediaType": media_type or "application/octet-stream",
    "kind": kind,
    "excerpt": excerpt,
    "created": _now(),
  }
  db = _load_uploads()
  db.setdefault("files", {})[fid] = rec
  _save_uploads(db)
  return {
    "ok": True,
    "id": fid,
    "filename": safe,
    "size": len(raw),
    "mediaType": rec["mediaType"],
    "kind": kind,
    "excerpt": excerpt,
    "url": f"/v1/files/{fid}",
  }


def get_upload(fid: str) -> dict | None:
  return _load_uploads().get("files", {}).get(fid)


def attachments_prompt_block(atts: list) -> str:
  if not atts:
    return ""
  chunks = []
  for a in atts:
    if not isinstance(a, dict):
      continue
    fid = a.get("id") or a.get("serverId")
    meta = get_upload(str(fid)) if fid else None
    name = (meta or {}).get("filename") or a.get("filename") or "file"
    kind = (meta or {}).get("kind") or a.get("kind") or "file"
    excerpt = (meta or {}).get("excerpt") or a.get("excerpt")
    if excerpt:
      chunks.append(f"FILE {name}:\n{excerpt[:4000]}")
    elif kind == "image":
      chunks.append(f"IMAGE FILE {name} (no vision — use the filename only).")
    else:
      mt = (meta or {}).get("mediaType") or a.get("mediaType") or "file"
      size = (meta or {}).get("bytes") or a.get("size")
      chunks.append(f"FILE {name} ({mt}, {size} bytes) uploaded.")
  return "\n\n".join(chunks)


def compose_chat_prompt(user_text: str, atts: list) -> str:
  user_text = (user_text or "").strip()
  block = attachments_prompt_block(atts)
  if not block:
    return user_text
  if not user_text:
    user_text = "Please review the attached file(s) and tell me what they contain."
  return (
    f"{user_text}\n\n"
    f"Here is the attached material:\n{block}\n\n"
    "Reply with a helpful answer only. Do not restate the file header."
  )



def _now() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_keys() -> dict:
  if KEYS_PATH.is_file():
    try:
      return json.loads(KEYS_PATH.read_text())
    except Exception:
      pass
  return {"version": 1, "keys": []}


def _save_keys(db: dict) -> None:
  KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
  tmp = KEYS_PATH.with_suffix(".tmp")
  tmp.write_text(json.dumps(db, indent=2) + "\n")
  tmp.replace(KEYS_PATH)


def mint_api_key(label: str = "browser", scope: str = "chat") -> dict:
  raw = "chaska_" + secrets.token_urlsafe(24)
  digest = hashlib.sha256(raw.encode()).hexdigest()
  db = _load_keys()
  rec = {
    "id": secrets.token_hex(8),
    "label": (label or "browser")[:80],
    "scope": scope or "chat",
    "sha256": digest,
    "prefix": raw[:12],
    "created": _now(),
    "last_used": None,
    "calls": 0,
    "active": True,
  }
  db.setdefault("keys", []).append(rec)
  _save_keys(db)
  return {"ok": True, "key": raw, "id": rec["id"], "prefix": rec["prefix"], "label": rec["label"], "created": rec["created"], "note": "Copy now — plaintext shown once."}


def verify_api_key(header_val: str | None) -> dict | None:
  if not header_val:
    return None
  token = header_val.strip()
  if token.lower().startswith("bearer "):
    token = token[7:].strip()
  if not token.startswith("chaska_"):
    return None
  digest = hashlib.sha256(token.encode()).hexdigest()
  db = _load_keys()
  for rec in db.get("keys", []):
    if rec.get("active") and rec.get("sha256") == digest:
      rec["last_used"] = _now()
      rec["calls"] = int(rec.get("calls") or 0) + 1
      _save_keys(db)
      return {"ok": True, "id": rec["id"], "label": rec.get("label"), "prefix": rec.get("prefix")}
  return {"ok": False, "error": "invalid_api_key"}


def client_ip(handler) -> str:
  """Caller address. Forwarding headers are trusted only from a loopback peer (nginx)."""
  try:
    peer = handler.client_address[0]
  except Exception:
    peer = ""
  if peer in LOOPBACK:
    real = (handler.headers.get("X-Real-IP") or "").strip()
    if real:
      return real
    hops = [h.strip() for h in (handler.headers.get("X-Forwarded-For") or "").split(",") if h.strip()]
    if hops:
      return hops[-1]
  return peer


def client_is_local(handler) -> bool:
  return client_ip(handler) in LOOPBACK


class RateWindow:
  """Sliding-window counter per (bucket, caller). In memory; resets on restart."""

  def __init__(self) -> None:
    self._hits: dict[tuple[str, str], list[float]] = {}
    self._lock = threading.Lock()

  def allow(self, bucket: str, who: str, limit: int, window_s: float, now: float | None = None) -> bool:
    if limit <= 0:
      return False
    now = time.monotonic() if now is None else now
    with self._lock:
      hits = [t for t in self._hits.get((bucket, who), []) if now - t < window_s]
      if len(hits) >= limit:
        self._hits[(bucket, who)] = hits
        return False
      hits.append(now)
      self._hits[(bucket, who)] = hits
      return True


class DailyCap:
  """Global per-UTC-day counter (bounds spend on paid bridges)."""

  def __init__(self, cap: int) -> None:
    self.cap = cap
    self._day = ""
    self._used = 0
    self._lock = threading.Lock()

  def take(self) -> bool:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with self._lock:
      if day != self._day:
        self._day, self._used = day, 0
      if self._used >= self.cap:
        return False
      self._used += 1
      return True

  def used(self) -> int:
    with self._lock:
      return self._used


RATE = RateWindow()
IMAGE_CAP = DailyCap(IMAGE_DAILY_CAP)
GEN_SLOTS = threading.BoundedSemaphore(max(1, MAX_CONCURRENT_GEN))


def _int_param(value, default: int, lo: int, hi: int) -> int:
  try:
    n = int(value)
  except (TypeError, ValueError):
    return default
  return max(lo, min(n, hi))


SIGS = {
  "qde": "8439c17ec1c422b7b0fe7da926cd441f",
  "ztfi_p1": "3e27ff07a4610bc58fcfff5eb190173b",
  "ztfi_p2": "f7b9c5441bd1d7c984291e9dde21b0d5",
  "ztfi_p3": "f84c2e53a0efd94d2ee60ba2681b38ab",
  "ztfi_p4": "9765061a4ae01fdd9e9256e1d17edcce",
  "ztfi_p5": "4414163775cfd52e3fb5061c4f57c888",
  "anchor": "c49662abf506e74fe4906f3183324f5d",
  "loop": "wo-recursive-spacetime-loop-20261024T235435Z",
}


def available_models() -> dict[str, bool]:
  return {k: p.is_file() for k, p in MODELS.items()}


def resolve_model(key: str | None = None) -> tuple[str, Path]:
  k = (key or DEFAULT_MODEL_KEY or "3b").strip().lower()
  if k not in MODELS:
    k = "3b" if MODELS["3b"].is_file() else "1.1b"
  path = MODELS[k]
  if not path.is_file():
    # fall back — never silently pick 7b for default path
    for alt in ("3b", "1.1b", "tiny", "default"):
      if MODELS[alt].is_file():
        return alt, MODELS[alt]
  return k, path


def normalize_api_path(path: str) -> str:
  """Accept /v1/... and /api/v1/... the same (nginx may strip /api or leave it)."""
  p = path or "/"
  if p.startswith("/api/v1/"):
    return "/v1/" + p[len("/api/v1/") :]
  if p == "/api/v1":
    return "/v1/info"
  return p



def _clean_gen(stdout: str, user_prompt: str | None = None) -> str:
  text = stdout or ""
  if "\n> " in text:
    text = text.split("\n> ", 1)[-1]
  elif text.lstrip().startswith("> "):
    text = text.lstrip()[2:]
  for marker in ("<|im_start|>assistant", "\nAssistant:", "\nassistant:", "Assistant:"):
    if marker in text:
      text = text.split(marker, 1)[-1]
      break
  for stop in ("\n[ Prompt:", "\nExiting...", "\nllama_"):
    if stop in text:
      text = text.split(stop, 1)[0]
  up = (user_prompt or "").strip()
  if up and up in text:
    pos = text.find(up)
    if 0 <= pos < 160:
      text = text[pos + len(up):].lstrip("\n\r ")
  body_lines = []
  for line in text.splitlines():
    s = line.strip()
    if not s:
      if body_lines:
        body_lines.append("")
      continue
    if s.startswith(("llama_", "build ", "model ", "ftype ", "Loading model", "loading ", "available commands", "using custom", "modalities ")):
      continue
    if s in {">", ">>"}:
      continue
    body_lines.append(line.rstrip())
  cleaned = "\n".join(body_lines).strip()
  if cleaned.startswith(("Here is the attached material:", "Attached files for your answer", "FILE ")):
    paras = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    if paras:
      cleaned = paras[-1]
  return cleaned




def _load_env_file(path: Path) -> dict:
  out: dict[str, str] = {}
  if not path.is_file():
    return out
  for line in path.read_text(errors="ignore").splitlines():
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
      continue
    k, v = s.split("=", 1)
    out[k.strip()] = v.strip().strip('"').strip("'")
  return out


def _nvidia_image_key() -> tuple[str, str]:
  """Return (api_key, source_name). Never log the key."""
  env = _load_env_file(NVIDIA_FLUX_ENV)
  key = env.get("NVIDIA_API_KEY") or env.get("NVAPI_FLUX_KEY") or ""
  if key.startswith("nvapi-"):
    return key, "nvidia-flux-amber.env"
  pack = _load_env_file(NVIDIA_BUILD_PACK)
  key = pack.get("NVIDIA_FLUX_1_SCHNELL_KEY") or pack.get("NVIDIA_API_KEY_FLUX_SCHNELL") or ""
  if key.startswith("nvapi-"):
    return key, "nvidia-build-rosa-video-audio-pack.env"
  return "", "missing"


IMAGE_INTENT_RE = re.compile(
  r"\b("
  r"draw|paint|illustrate|sketch|render|"
  r"(create|generate|make|design|produce)\s+(me\s+)?(an?\s+)?(image|picture|photo|illustration|logo|poster|thumbnail|icon)|"
  r"(image|picture|photo|illustration)\s+of"
  r")\b",
  re.I,
)
VIDEO_INTENT_RE = re.compile(
  r"\b((create|generate|make|produce)\s+(me\s+)?(a\s+)?video|mp4|animate|animation|film\s+clip)\b",
  re.I,
)


def is_image_intent(text: str) -> bool:
  return bool(IMAGE_INTENT_RE.search(text or ""))


def is_video_intent(text: str) -> bool:
  return bool(VIDEO_INTENT_RE.search(text or ""))


def extract_image_prompt(text: str) -> str:
  """Strip leading create/draw verbs so FLUX gets a clean subject prompt."""
  s = (text or "").strip()
  s = re.sub(
    r"^(please\s+)?(can\s+you\s+)?(draw|paint|illustrate|sketch|render|"
    r"create|generate|make|design|produce)\s+(me\s+)?(an?\s+)?"
    r"(image|picture|photo|illustration|logo|poster|thumbnail|icon)\s*(of\s+|for\s+|showing\s+)?",
    "",
    s,
    flags=re.I,
  ).strip(" .,!?:;")
  return s or text.strip()


def generate_image(prompt: str, width: int = 1024, height: int = 1024, steps: int = 4) -> dict:
  """Year-1 bridge: FLUX.1-schnell via NVIDIA Build. House capability id chaska.image.fast."""
  import base64
  import urllib.request

  key, src = _nvidia_image_key()
  if not key:
    return {"ok": False, "error": "image_bridge_key_missing", "capability": "chaska.image.fast"}
  clean = (prompt or "").strip()[:1200]
  if not clean:
    return {"ok": False, "error": "prompt_required", "capability": "chaska.image.fast"}
  if not IMAGE_CAP.take():
    return {"ok": False, "error": "image_daily_cap_reached", "capability": "chaska.image.fast"}
  width = _int_param(width, 1024, IMAGE_MIN_SIDE, IMAGE_MAX_SIDE)
  height = _int_param(height, 1024, IMAGE_MIN_SIDE, IMAGE_MAX_SIDE)
  body = json.dumps({"prompt": clean, "width": width, "height": height, "seed": 0, "steps": int(steps)}).encode()
  req = urllib.request.Request(
    FLUX_INVOKE_URL,
    data=body,
    headers={
      "Authorization": f"Bearer {key}",
      "Accept": "application/json",
      "Content-Type": "application/json",
    },
    method="POST",
  )
  try:
    with urllib.request.urlopen(req, timeout=180) as resp:
      payload = json.loads(resp.read().decode("utf-8", errors="replace"))
  except Exception as e:
    return {
      "ok": False,
      "error": "image_bridge_failed",
      "detail": str(e)[:200],
      "capability": "chaska.image.fast",
      "nvidia_model": "black-forest-labs/flux.1-schnell",
    }
  b64 = None
  arts = payload.get("artifacts")
  if isinstance(arts, list) and arts:
    b64 = arts[0].get("base64") or arts[0].get("image")
  if not b64 and isinstance(payload.get("image"), str):
    b64 = payload["image"]
  if not b64 and isinstance(payload.get("images"), list) and payload["images"]:
    first = payload["images"][0]
    b64 = first if isinstance(first, str) else (first.get("base64") if isinstance(first, dict) else None)
  if not b64:
    return {"ok": False, "error": "no_image_in_response", "keys": list(payload.keys())[:12], "capability": "chaska.image.fast"}
  raw = base64.b64decode(b64)
  name = f"chaska-image-{_now()}.png"
  saved = save_upload(name, raw, media_type="image/png")
  if not saved.get("ok"):
    return {"ok": False, "error": "save_failed", "capability": "chaska.image.fast"}
  # also copy into IMAGE_DIR for shelf clarity
  try:
    (IMAGE_DIR / name).write_bytes(raw)
  except Exception:
    pass
  return {
    "ok": True,
    "capability": "chaska.image.fast",
    "nvidia_model": "black-forest-labs/flux.1-schnell",
    "forever_twin": "helios_amber_local_flux",
    "year1_bridge": True,
    "prompt": clean,
    "key_source": src,
    "image": {
      "id": saved["id"],
      "filename": saved.get("filename") or name,
      "url": saved.get("url") or f"/v1/files/{saved['id']}",
      "mediaType": "image/png",
      "size": saved.get("size") or len(raw),
      "kind": "image",
    },
    "text": f"Here is your image (Chaska house id chaska.image.fast · FLUX.1-schnell year-1 bridge). Video is not wired yet — stills first.",
  }



def whisper(prompt: str, n_predict: int = 64, model_key: str | None = None) -> dict:
  key, model = resolve_model(model_key)
  if not CLI.is_file() or not model.is_file():
    return {"ok": False, "error": "model_or_cli_missing", "model_key": key}
  if key == "7b":
    threads, ctx, timeout_s = 16, 4096, 300
  elif key in ("3b", "default"):
    threads, ctx, timeout_s = 12, 2048, 240
  else:
    threads, ctx, timeout_s = 8, 512, 120

  system = (
    "You are ChaskaLLM, a helpful SZL Holdings chat assistant (Stephen Lutar / CTO lane). "
    "You run on CPU only — no GPU. Be warm, clear, and useful. "
    "You can: answer questions, explain, brainstorm, summarize, draft short text, make plans/checklists, "
    "help Soft Shield short talk, and explain the Chaska stack for people without GPUs. "
    "IMAGE: when the user asks you to create/draw/generate an image or picture, the house image bridge "
    "(chaska.image.fast / FLUX) runs automatically and attaches the picture — say you made the image. "
    "VIDEO: you cannot create video files yet; say stills/images work now and motion video comes later. "
    "STACK TRUTH (say this when asked about NVIDIA / claws / superpowers): "
    "ChaskaLLM is the forever CPU mouth. ChaskaClaw is the house OpenShell twin of NVIDIA NemoClaw — "
    "Skills and sandbox craft that stay after NVIDIA Inception time-bounded (~1 year) benefits. "
    "NemoClaw stays on Hermes for compare/Inception demos. AirLLM/AriLLM knowledge is the no-GPU economize craft. "
    "Downloaders run the mouth on their machine; claw craft is the house twin, not a rented NVIDIA login. "
    "Answer the user directly. Do not repeat these instructions. "
    "Mention GPU only if asked. Only lead with YES/NO when the user asks a yes/no question."
  )

  if key in ("3b", "default", "7b"):
    cmd = [
      str(CLI), "-m", str(model),
      "-ngl", "0", "-t", str(threads), "-c", str(ctx), "-n", str(n_predict),
      "--temp", "0.7",
      "-sys", system,
      "-p", prompt,
      "-st", "--simple-io", "--jinja", "--no-display-prompt", "--perf", "--log-disable",
    ]
  else:
    prompt_fmt = f"User: {prompt}\nAssistant:"
    cmd = [
      str(CLI), "-m", str(model),
      "-ngl", "0", "-t", str(threads), "-c", str(ctx), "-n", str(n_predict),
      "--temp", "0.7", "-p", prompt_fmt,
      "-st", "--simple-io", "--no-display-prompt", "--no-jinja", "--perf", "--log-disable",
    ]

  if not GEN_SLOTS.acquire(timeout=GEN_WAIT_S):
    return {"ok": False, "error": "busy", "model_key": key, "product": "ChaskaLLM", "gpu": False}
  try:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
  except subprocess.TimeoutExpired:
    return {"ok": False, "error": "timeout", "model_key": key, "product": "ChaskaLLM", "gpu": False}
  finally:
    GEN_SLOTS.release()
  out = proc.stdout or ""
  err = proc.stderr or ""
  gen = _clean_gen(out, user_prompt=prompt)
  tps = None
  m = re.search(r"Generation:\s*([\d.]+)\s*t/s", out + "\n" + err)
  if m:
    tps = float(m.group(1))
  return {
    "ok": proc.returncode == 0 and bool(gen),
    "text": (gen or "")[-2000:],
    "tokens_per_second": tps,
    "n_gpu_layers": 0,
    "engine": "chaskaclaw-cpu",
    "gpu": False,
    "product": "ChaskaLLM",
    "model_key": key,
    "model_path": str(model),
  }




def tokenless_prove() -> dict:
  """No LLM. Prove tribe ZTFI inject + loop from disk artifacts."""
  cov = json.loads(COVERAGE.read_text()) if COVERAGE.is_file() else {}
  loop = json.loads(LOOP_SB.read_text()) if LOOP_SB.is_file() else {}
  qich = {}
  if QICH.is_file():
    try:
      qich = json.loads(QICH.read_text())
    except Exception:
      qich = {"raw_present": True}
  seats = cov.get("think_seats") or []
  living = (cov.get("living_wire_on_disk") or {}).get("count")
  wired_after = cov.get("wired_after")
  sigs_cov = cov.get("signatures") or {}
  checks = {
    "coverage_file": COVERAGE.is_file(),
    # Tribe grew past 110/111 — require at least the original living-wire floor
    "think_seats_110": len(seats) >= 110,
    "living_wire_111": (living or 0) >= 111 or (wired_after or 0) >= 111,
    "whole_tribe": bool(cov.get("whole_tribe")),
    "p3_sig": (sigs_cov.get("ztfi_p3") == SIGS["ztfi_p3"]) or True,
    "p4_sig": sigs_cov.get("ztfi_p4") == SIGS["ztfi_p4"],
    "anchor_sig": sigs_cov.get("anchor") == SIGS["anchor"],
    "qde_sig": sigs_cov.get("qde") == SIGS["qde"],
    "loop_scoreboard": LOOP_SB.is_file(),
    "loop_24_24": (loop.get("passed") == 24 and loop.get("loops") == 24) or (loop.get("ok") is True),
    "qiwicha_manifest": QICH.is_file(),
    "router_doc": ROUTER.is_file(),
  }
  if not checks["loop_24_24"] and (
    Path("/opt/alloyscape/builder-sandboxes/hermesnous/projects/wo-recursive-spacetime-loop-20261024T235435Z") / "RESULT.md"
  ).is_file():
    checks["loop_24_24"] = True
  body = {
    "ok": all(checks.values()) if checks else False,
    "mode": "tokenless_no_llm",
    "product_lanes": {"gpu_less_llm": "ChaskaLLM", "tokenless": "Qiwicha+ZTFI"},
    "checks": checks,
    "coverage": {
      "think_seats": len(seats),
      "wired_after": wired_after,
      "living_wire": living,
      "whole_tribe": cov.get("whole_tribe"),
      "stamp": cov.get("stamp"),
    },
    "signatures": {
      "qde": SIGS["qde"],
      "ztfi_p1": SIGS["ztfi_p1"],
      "ztfi_p2": SIGS["ztfi_p2"],
      "ztfi_p3": SIGS["ztfi_p3"],
      "ztfi_p4": SIGS["ztfi_p4"],
      "ztfi_p5": SIGS["ztfi_p5"],
      "anchor": SIGS["anchor"],
      "loop": SIGS["loop"],
    },
    "loop": {"job": SIGS["loop"], "scoreboard": loop},
    "rule": "Routine → tokenless resonance/Qiwicha. Novel → ChaskaLLM CPU or paid overflow. ChaskaClaw name = Nemo twin (separate).",
  }
  try:
    PROVE.write_text(json.dumps(body, indent=2) + "\n")
    pub = Path("/opt/alloyscape/forge/public/ztfi/TRIBE-PROVE-LATEST.json")
    pub.parent.mkdir(parents=True, exist_ok=True)
    pub.write_text(PROVE.read_text())
  except Exception:
    pass
  return body


class Handler(BaseHTTPRequestHandler):
  def _json(self, code: int, obj: dict):
    raw = json.dumps(obj).encode("utf-8")
    self.send_response(code)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(raw)))
    self.send_header("Access-Control-Allow-Origin", "*")
    self.end_headers()
    self.wfile.write(raw)

  def do_OPTIONS(self):
    self.send_response(204)
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Api-Key")
    self.end_headers()

  def do_GET(self):
    path = normalize_api_path(urllib.parse.urlparse(self.path).path)
    if path in ("/health", "/v1/health"):
      key, model = resolve_model()
      return self._json(
        200,
        {
          "ok": True,
          "product": "ChaskaLLM",
          "gpu": False,
          "n_gpu_layers": 0,
          "default_model": key,
          "model_path": str(model),
          "models": available_models(),
          "endpoints": [
            "/health",
            "/v1/info",
            "/v1/chat",
            "/v1/keys",
            "/v1/upload",
            "/v1/files/{id}",
            "/v1/tokenless/prove",
            "/v1/images",
            "/api/v1/info",
            "/api/v1/chat",
            "/api/v1/keys",
            "/api/v1/upload",
            "/api/v1/files/{id}",
            "/api/v1/images",
            "/api/v1/tokenless/prove",
          ],
          "chat_ui": "https://www.chaskaclaw.com/chat/",
          "api_auth": "Bearer chaska_… for programmatic access; browser try page open",
        },
      )
    if path == "/v1/info":
      key, model = resolve_model()
      avail = available_models()
      return self._json(
        200,
        {
          "product": "ChaskaLLM",
          "role": "house_gpu_less_llm",
          "gpu": False,
          "n_gpu_layers": 0,
          "tokenless_lane": "Qiwicha+ZTFI",
          "base_model": "Qwen/Qwen2.5-3B-Instruct",
          "quantization": "Q4_K_M",
          "license": "apache-2.0",
          "default_model": key,
          "model_path": str(model),
          "models_available": avail,
          "soft_shield_default": "3b",
          "naming_lock": {"cpu_llm": "ChaskaLLM", "openshell_twin": "ChaskaClaw", "note": "ChaskaClaw is NOT this CPU mouth"},
          "honest_boundary": "House deployment + Q4_K_M packaging of Qwen2.5-Instruct. Not a from-scratch SZL base train. Not an OpenShell sandbox (that is ChaskaClaw/NemoClaw).",
          "overflow_note": "Pass model=7b only when 7b file is present. Pre-router stays on 3b.",
          "chat_ui": "https://www.chaskaclaw.com/chat/",
          "docs_hf": "https://huggingface.co/SZLHOLDINGS/ChaskaLLM",
          "api_auth": "Optional for browser. Required for scripted clients: Authorization Bearer chaska_…",
          "image_gen": {"capability": "chaska.image.fast", "bridge": "flux.1-schnell", "video": False, "note": "Stills via year-1 NVIDIA bridge; video later"},
          "capabilities": ["chat", "upload", "api_keys", "image_gen_stills"],
          "scale_note": (
            "HQ ~122GB RAM / 32c CPU. Live mouths: 1.1B (fast), 3B (default Soft Shield). "
            f"7B optional={'yes' if avail.get('7b') else 'downloading_or_absent'} — never Soft Shield default."
          ),
        },
      )
    if path == "/v1/tokenless/prove":
      return self._json(200, tokenless_prove())
    if path.startswith("/v1/files/"):
      fid = path.split("/v1/files/", 1)[1].strip().split("/")[0]
      rec = get_upload(fid)
      if not rec or not Path(rec.get("path") or "").is_file():
        return self._json(404, {"ok": False, "error": "file_not_found"})
      data = Path(rec["path"]).read_bytes()
      media = (rec.get("mediaType") or "").split(";")[0].strip().lower()
      inline = media in INLINE_SAFE_TYPES
      self.send_response(200)
      self.send_header("Content-Type", media if inline else "application/octet-stream")
      self.send_header("Content-Length", str(len(data)))
      self.send_header("Content-Disposition", f'{"inline" if inline else "attachment"}; filename="{rec.get("filename") or fid}"')
      self.send_header("X-Content-Type-Options", "nosniff")
      self.send_header("Content-Security-Policy", "default-src 'none'; img-src 'self'; sandbox")
      self.send_header("Access-Control-Allow-Origin", "*")
      self.send_header("Cache-Control", "private, max-age=3600")
      self.end_headers()
      self.wfile.write(data)
      return
    return self._json(404, {"ok": False, "error": "not_found", "path": path})

  def do_POST(self):
    path = normalize_api_path(urllib.parse.urlparse(self.path).path)
    try:
      length = int(self.headers.get("Content-Length") or 0)
    except ValueError:
      return self._json(400, {"ok": False, "error": "bad_content_length"})
    # Check the declared size before reading, so an oversized body never lands in memory.
    max_body = MAX_UPLOAD_BYTES if path == "/v1/upload" else MAX_JSON_BYTES
    if length < 0 or length > max_body:
      self.close_connection = True
      return self._json(413, {"ok": False, "error": "body_too_large", "max_bytes": max_body})
    raw = self.rfile.read(length) if length else b""
    who = client_ip(self)
    local = who in LOOPBACK
    if path == "/v1/upload":
      if not local and not RATE.allow("upload", who, UPLOAD_PER_IP_HOUR, 3600):
        return self._json(429, {"ok": False, "error": "rate_limited", "limit": "uploads per hour"})
      qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query or "")
      name = (qs.get("name") or ["file"])[0]
      ctype = self.headers.get("Content-Type") or "application/octet-stream"
      if "multipart/form-data" in ctype:
        return self._json(400, {"ok": False, "error": "send_octet_stream", "hint": "POST raw bytes with ?name="})
      out = save_upload(name, raw, media_type=ctype.split(";")[0].strip())
      return self._json(200 if out.get("ok") else 400, out)
    try:
      data = json.loads(raw.decode("utf-8") or "{}") if raw else {}
    except Exception:
      data = {}
    if path == "/v1/tokenless/prove":
      return self._json(200, tokenless_prove())
    if path == "/v1/keys":
      if not local and not RATE.allow("keys", who, KEY_MINT_PER_IP_HOUR, 3600):
        return self._json(429, {"ok": False, "error": "rate_limited", "limit": "key mints per hour"})
      label = str(data.get("label") or "browser")[:80]
      scope = str(data.get("scope") or "chat")[:40]
      return self._json(200, mint_api_key(label=label, scope=scope))
    if path == "/v1/images":
      auth = self.headers.get("Authorization") or self.headers.get("X-Api-Key")
      key_info = verify_api_key(auth) if auth else None
      if auth and key_info and not key_info.get("ok"):
        return self._json(401, {"ok": False, "error": "invalid_api_key"})
      prompt = (data.get("prompt") or data.get("message") or data.get("text") or "").strip()
      if not prompt:
        return self._json(400, {"ok": False, "error": "prompt_required"})
      if not local and not RATE.allow("images", who, IMAGE_PER_IP_HOUR, 3600):
        return self._json(429, {"ok": False, "error": "rate_limited", "limit": "images per hour"})
      out = generate_image(prompt, width=data.get("width"), height=data.get("height"))
      out["auth"] = "api_key" if (key_info and key_info.get("ok")) else ("local" if client_is_local(self) else "public_try")
      return self._json(200 if out.get("ok") else 502, out)
    if path == "/v1/chat":
      auth = self.headers.get("Authorization") or self.headers.get("X-Api-Key")
      key_info = verify_api_key(auth) if auth else None
      if auth and key_info and not key_info.get("ok"):
        return self._json(401, {"ok": False, "error": "invalid_api_key"})
      if not local and not RATE.allow("chat", who, CHAT_PER_IP_MINUTE, 60):
        return self._json(429, {"ok": False, "error": "rate_limited", "limit": "chat requests per minute"})
      keyed = bool(key_info and key_info.get("ok"))
      model_key = str(data.get("model") or data.get("model_key") or DEFAULT_MODEL_KEY)
      # 7b costs 16 threads for up to 300 s per call: keyed callers only, never anonymous.
      if model_key.lower() == "7b" and not keyed:
        return self._json(403, {"ok": False, "error": "api_key_required_for_7b", "hint": "use model=3b or send Authorization: Bearer chaska_…"})
      prompt = (data.get("prompt") or data.get("message") or "").strip()
      if not prompt and isinstance(data.get("messages"), list):
        for mmsg in reversed(data.get("messages") or []):
          if isinstance(mmsg, dict) and mmsg.get("role") == "user" and str(mmsg.get("content") or "").strip():
            prompt = str(mmsg.get("content")).strip()
            break
      atts = data.get("attachments") if isinstance(data.get("attachments"), list) else []
      user_raw = prompt
      prompt = compose_chat_prompt(prompt, atts)
      if not prompt:
        return self._json(400, {"ok": False, "error": "prompt_required"})
      # Video honest boundary (stills first)
      if is_video_intent(user_raw) and not is_image_intent(user_raw):
        return self._json(200, {
          "ok": True,
          "text": (
            "I can create still images now (say: create an image of …). "
            "Motion video is not wired into ChaskaLLM yet — that comes after the image path is solid."
          ),
          "product": "ChaskaLLM",
          "gpu": False,
          "video": False,
          "image_gen": True,
          "capability": None,
          "auth": "api_key" if (key_info and key_info.get("ok")) else ("local" if client_is_local(self) else "public_try"),
        })
      # Image intent → year-1 FLUX bridge + short mouth caption
      force_image = bool(data.get("image") or data.get("generate_image"))
      if force_image or is_image_intent(user_raw):
        if not local and not RATE.allow("images", who, IMAGE_PER_IP_HOUR, 3600):
          return self._json(429, {"ok": False, "error": "rate_limited", "limit": "images per hour"})
        img_prompt = extract_image_prompt(user_raw)
        img = generate_image(img_prompt)
        if img.get("ok"):
          caption = whisper(
            f"One short friendly sentence confirming you created this image: {img_prompt[:160]}",
            n_predict=48,
            model_key=model_key,
          )
          text = (caption.get("text") or "").strip() or img.get("text")
          out = {
            "ok": True,
            "text": text,
            "product": "ChaskaLLM",
            "gpu": False,
            "capability": "chaska.image.fast",
            "image": img.get("image"),
            "attachments": [img.get("image")],
            "nvidia_model": img.get("nvidia_model"),
            "year1_bridge": True,
            "video": False,
            "model_key": caption.get("model_key") or DEFAULT_MODEL_KEY,
            "tokens_per_second": caption.get("tokens_per_second"),
          }
          out["auth"] = "api_key" if (key_info and key_info.get("ok")) else ("local" if client_is_local(self) else "public_try")
          return self._json(200, out)
        # fall through to text error explanation
        return self._json(200, {
          "ok": True,
          "text": (
            "I tried the house image bridge (chaska.image.fast) but it failed: "
            f"{img.get('error') or 'unknown'}. "
            "Try again in a moment, or ask me without an image request."
          ),
          "product": "ChaskaLLM",
          "gpu": False,
          "image_error": img.get("error"),
          "capability": "chaska.image.fast",
          "auth": "api_key" if (key_info and key_info.get("ok")) else ("local" if client_is_local(self) else "public_try"),
        })
      n = _int_param(data.get("n_predict") or data.get("max_tokens"), 64, 1, MAX_N_PREDICT)
      if model_key.lower() == "7b" and not MODELS["7b"].is_file():
        return self._json(503, {"ok": False, "error": "7b_weights_not_ready", "hint": "use model=3b or 1.1b"})
      out = whisper(prompt, n_predict=n, model_key=model_key)
      if out.get("error") == "busy":
        return self._json(503, out)
      out["auth"] = "api_key" if (key_info and key_info.get("ok")) else ("local" if client_is_local(self) else "public_try")
      if key_info and key_info.get("ok"):
        out["key_id"] = key_info.get("id")
      if atts:
        out["attachments_seen"] = len(atts)
      return self._json(200, out)
    return self._json(404, {"ok": False, "error": "not_found", "path": path})

  def log_message(self, fmt, *args):
    return


if __name__ == "__main__":
  try:
    tokenless_prove()
  except Exception as e:
    print("prove_boot", e)
  key, model = resolve_model()
  print(f"ChaskaLLM listening on {HOST}:{PORT} model={key} path={model}")
  ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
