import asyncio
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

from . import db, sd

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/models"))
IMAGES_DIR = Path(os.environ.get("IMAGES_DIR", "/images"))
GEN_DIR = IMAGES_DIR / "generados"
REF_DIR = IMAGES_DIR / "referencia"
MODEL_EXTS = {".safetensors", ".ckpt", ".gguf"}
SAMPLER = "euler_a"

# SD 1.5 rinde mejor cerca de 512 px; todas las medidas son múltiplos de 64
ASPECTS = {
    "1:1": (512, 512), "3:4": (512, 704), "4:3": (704, 512),
    "2:3": (512, 768), "3:2": (768, 512), "9:16": (448, 768), "16:9": (768, 448),
}

queue: asyncio.Queue = asyncio.Queue()
progress: dict[int, tuple[int, int]] = {}


@asynccontextmanager
async def lifespan(_app):
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    REF_DIR.mkdir(parents=True, exist_ok=True)
    await db.init()
    worker_task = asyncio.create_task(worker())
    yield
    worker_task.cancel()
    await db.pool.close()


app = FastAPI(title="Gen AI", lifespan=lifespan)
app.mount("/api/files", StaticFiles(directory=IMAGES_DIR), name="files")


def to_url(path):
    """/images/generados/x.png -> /api/files/generados/x.png"""
    if not path:
        return None
    return "/api/files/" + str(Path(path).relative_to(IMAGES_DIR))


def serialize(row):
    row = dict(row)
    row["created_at"] = row["created_at"].isoformat()
    row["output_url"] = to_url(row["output_path"])
    row["reference_url"] = to_url(row["reference_path"])
    step, total = progress.get(row["id"], (0, row["steps"]))
    row["progress"] = {"step": step, "total": total}
    return row


def list_models():
    if not MODELS_DIR.exists():
        return []
    return sorted(p.name for p in MODELS_DIR.iterdir() if p.suffix.lower() in MODEL_EXTS)


def fit_dims(w, h):
    """Mantiene la proporción de la referencia: lado corto 512 y lado largo 768 como máximo."""
    s = min(512 / min(w, h), 768 / max(w, h))
    return max(64, round(w * s / 64) * 64), max(64, round(h * s / 64) * 64)


def new_name():
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.png"


async def worker():
    """Procesa la cola de una en una: hay una sola GPU."""
    while True:
        gen_id = await queue.get()
        try:
            await process(gen_id)
        except Exception as e:  # el worker no debe morir nunca
            await db.execute("UPDATE generations SET status='error', error=%s WHERE id=%s", (str(e), gen_id))
        finally:
            progress.pop(gen_id, None)
            queue.task_done()


async def process(gen_id):
    g = await db.fetch_one("SELECT * FROM generations WHERE id=%s", (gen_id,))
    if not g:
        return
    await db.execute("UPDATE generations SET status='running' WHERE id=%s", (gen_id,))
    progress[gen_id] = (0, g["steps"])
    output_path = GEN_DIR / new_name()
    started = time.monotonic()
    try:
        await sd.run(
            model_path=str(MODELS_DIR / g["model"]),
            prompt=g["prompt"], negative_prompt=g["negative_prompt"],
            width=g["width"], height=g["height"], steps=g["steps"],
            cfg_scale=g["cfg_scale"], seed=g["seed"], sampler=g["sampler"],
            output_path=str(output_path),
            init_image=g["reference_path"], strength=g["strength"],
            on_progress=lambda step, total: progress.__setitem__(gen_id, (step, total)) if total <= g["steps"] else None,
        )
    except sd.SdError as e:
        await db.execute("UPDATE generations SET status='error', error=%s WHERE id=%s", (str(e), gen_id))
        return
    await db.execute(
        "UPDATE generations SET status='done', output_path=%s, duration_ms=%s WHERE id=%s",
        (str(output_path), int((time.monotonic() - started) * 1000), gen_id),
    )


@app.get("/api/health")
async def health():
    return {"ok": True, "queue": queue.qsize()}


@app.get("/api/models")
async def models():
    return list_models()


@app.post("/api/generate", status_code=202)
async def generate(
    prompt: str = Form(...),
    negative_prompt: str = Form("lowres, blurry, bad anatomy, deformed, watermark, text"),
    model: Optional[str] = Form(None),
    aspect: str = Form("1:1"),
    steps: int = Form(25),
    cfg_scale: float = Form(7.0),
    seed: int = Form(-1),
    strength: float = Form(0.6),
    reference: Optional[UploadFile] = File(None),
    reference_id: Optional[int] = Form(None),
):
    """Encola una generación. Referencia opcional: archivo subido o el resultado de una generación previa."""
    available = list_models()
    if not available:
        raise HTTPException(400, "No hay modelos en ./models")
    model = model or available[0]
    if model not in available:
        raise HTTPException(400, f"Modelo desconocido: {model}")
    if not prompt.strip():
        raise HTTPException(400, "El prompt es obligatorio")
    if not 1 <= steps <= 150:
        raise HTTPException(400, "steps debe estar entre 1 y 150")
    if not 0 < strength <= 1:
        raise HTTPException(400, "strength debe estar entre 0 y 1")

    reference_path, parent_id = None, None
    if reference is not None and reference.filename:
        try:
            img = ImageOps.exif_transpose(Image.open(reference.file)).convert("RGB")
        except Exception:
            raise HTTPException(400, "La referencia no es una imagen válida")
        reference_path = REF_DIR / new_name()
        img.save(reference_path)
    elif reference_id is not None:
        parent = await db.fetch_one("SELECT output_path FROM generations WHERE id=%s AND status='done'", (reference_id,))
        if not parent or not Path(parent["output_path"]).exists():
            raise HTTPException(404, "La generación de referencia no existe o no tiene imagen")
        reference_path, parent_id = Path(parent["output_path"]), reference_id

    if reference_path:
        with Image.open(reference_path) as img:
            width, height = fit_dims(*img.size)
    elif aspect in ASPECTS:
        width, height = ASPECTS[aspect]
    else:
        raise HTTPException(400, f"Relación de aspecto no válida: {aspect}")

    if seed < 0:
        seed = random.randint(0, 2**31 - 1)

    row = await db.fetch_one(
        """INSERT INTO generations
           (prompt, negative_prompt, model, width, height, steps, cfg_scale, seed, sampler,
            strength, reference_path, parent_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (prompt.strip(), negative_prompt.strip(), model, width, height, steps, cfg_scale, seed, SAMPLER,
         strength if reference_path else None, str(reference_path) if reference_path else None, parent_id),
    )
    await queue.put(row["id"])
    return serialize(row)


@app.get("/api/generations")
async def generations(limit: int = 60, offset: int = 0):
    rows = await db.fetch_all(
        "SELECT * FROM generations ORDER BY created_at DESC LIMIT %s OFFSET %s", (min(limit, 200), offset)
    )
    return [serialize(r) for r in rows]


@app.get("/api/generations/{gen_id}")
async def generation(gen_id: int):
    row = await db.fetch_one("SELECT * FROM generations WHERE id=%s", (gen_id,))
    if not row:
        raise HTTPException(404, "No existe")
    return serialize(row)


async def remove_unused_files(paths):
    """Borra del volumen las imágenes que ya no usa ninguna fila (ni como resultado ni como referencia)."""
    for path in {p for p in paths if p}:
        used = await db.fetch_one(
            "SELECT 1 FROM generations WHERE output_path=%s OR reference_path=%s LIMIT 1", (path, path)
        )
        if not used:
            Path(path).unlink(missing_ok=True)


@app.delete("/api/generations/{gen_id}", status_code=204)
async def delete_generation(gen_id: int):
    row = await db.fetch_one("SELECT * FROM generations WHERE id=%s", (gen_id,))
    if not row:
        raise HTTPException(404, "No existe")
    if row["status"] in ("queued", "running"):
        raise HTTPException(409, "No se puede borrar mientras se está generando")
    await db.execute("DELETE FROM generations WHERE id=%s", (gen_id,))
    await remove_unused_files([row["output_path"], row["reference_path"]])


@app.delete("/api/generations")
async def delete_all_generations():
    """Borra todo el historial salvo lo que está en cola o generándose."""
    rows = await db.fetch_all(
        "DELETE FROM generations WHERE status NOT IN ('queued', 'running') RETURNING output_path, reference_path"
    )
    await remove_unused_files([p for r in rows for p in (r["output_path"], r["reference_path"])])
    return {"deleted": len(rows)}
