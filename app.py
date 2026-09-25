import json
import os
import secrets
import shutil
import threading
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from processor import get_barcodes, remove_background, make_jpg, create_zip

ROOT = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent / "data")).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
BASE = Path(__file__).resolve().parent
ACCESS_KEY = os.getenv("APP_PASSWORD", "")
MAX_PAIRS = 400
MAX_FILE = 15 * 1024 * 1024
LOCK = threading.Lock()
app = FastAPI(title="La Casa de la Economía — Procesador Masivo")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


def auth(key):
    if not ACCESS_KEY:
        raise HTTPException(503, "Configura APP_PASSWORD en el servidor antes de usar la aplicación")
    if not secrets.compare_digest(key or "", ACCESS_KEY):
        raise HTTPException(401, "Contraseña incorrecta")


def directory(job):
    if not len(job) == 32 or any(c not in "0123456789abcdef" for c in job):
        raise HTTPException(400, "Lote inválido")
    p = ROOT / job
    if not p.is_dir():
        raise HTTPException(404, "No se encontró el lote")
    return p


def load(p):
    return json.loads((p / "status.json").read_text(encoding="utf8"))


def write(p, status):
    f = p / "status.tmp"
    f.write_text(json.dumps(status, ensure_ascii=False), encoding="utf8")
    f.replace(p / "status.json")


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE / "static" / "index.html").read_text(encoding="utf8")


@app.post("/api/jobs")
def start(x_app_key: str | None = Header(None)):
    auth(x_app_key)
    job = secrets.token_hex(16)
    p = ROOT / job
    (p / "uploads").mkdir(parents=True)
    (p / "results").mkdir()
    write(p, {"job": job, "state": "uploading", "received": 0, "finished": 0, "ok": 0, "failed": 0, "total": 0, "message": "Esperando las fotografías"})
    return {"job": job}


@app.post("/api/jobs/{job}/upload")
async def upload(job: str, index: int = Form(...), product: UploadFile = File(...), barcode: UploadFile = File(...), x_app_key: str | None = Header(None)):
    auth(x_app_key)
    p = directory(job)
    if not 0 <= index < MAX_PAIRS:
        raise HTTPException(400, "Límite de 400 productos por lote")
    with LOCK:
        state = load(p)
        if state["state"] != "uploading":
            raise HTTPException(409, "El procesamiento ya comenzó")
    folder = p / "uploads"
    names = []
    for tag, upload_file in (("producto", product), ("codigo", barcode)):
        if not (upload_file.content_type or "").startswith("image/"):
            raise HTTPException(400, "Solo se aceptan imágenes")
        # force image validation so arbitrary file names cannot be uploaded as images
        name = f"{index:04d}_{tag}.jpg"
        dest = folder / name
        length = 0
        with dest.open("wb") as out:
            while block := await upload_file.read(1024 * 1024):
                length += len(block)
                if length > MAX_FILE:
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, "Una imagen supera los 15 MB")
                out.write(block)
        try:
            from PIL import Image
            with Image.open(dest) as im:
                im.verify()
        except Exception:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "El archivo no contiene una imagen válida")
        names.append(name)
    with LOCK:
        state = load(p)
        state["received"] = len(list(folder.glob("*_producto.jpg")))
        write(p, state)
    return {"index": index, "received": state["received"]}


def worker(p: Path, total: int):
    rows = []
    seen = set()
    state = load(p)
    state.update(state="processing", total=total, message="Procesando fotografías")
    write(p, state)
    for i in range(total):
        product = p / "uploads" / f"{i:04d}_producto.jpg"
        code_photo = p / "uploads" / f"{i:04d}_codigo.jpg"
        row = {"par": i + 1, "foto_producto": product.name, "foto_codigo": code_photo.name,
               "codigo_detectado": "", "estado": "PENDIENTE", "detalle": "", "archivo_jpg": ""}
        try:
            if not product.exists() or not code_photo.exists():
                raise ValueError("Falta una de las dos fotografías")
            codes = get_barcodes(code_photo)
            if len(codes) != 1:
                raise ValueError("Código ilegible" if not codes else "Se detectaron varios códigos: " + ", ".join(codes))
            code = codes[0]
            row["codigo_detectado"] = code
            if code in seen:
                raise ValueError("Código repetido en este lote; revisar antes de asignar el JPG")
            seen.add(code)
            photo = remove_background(product)
            jpg = make_jpg(photo)
            filename = code + ".jpg"
            (p / "results" / filename).write_bytes(jpg)
            row.update(estado="OK", archivo_jpg=filename, detalle=f"{len(jpg) / 1024:.1f} KB")
            state["ok"] += 1
        except Exception as e:
            row["detalle"] = str(e)[:250]
            state["failed"] += 1
        rows.append(row)
        state["finished"] = i + 1
        state["message"] = f"Procesados {i + 1} de {total} productos"
        write(p, state)
    try:
        create_zip(p, rows, p / "catalogo_casa_economia.zip")
        state.update(state="done", message="ZIP listo para descargar")
    except Exception as e:
        state.update(state="error", message=f"Error creando ZIP: {e}")
    write(p, state)


@app.post("/api/jobs/{job}/process")
def process(job: str, total: int = Form(...), x_app_key: str | None = Header(None)):
    auth(x_app_key)
    p = directory(job)
    if not 1 <= total <= MAX_PAIRS:
        raise HTTPException(400, "Se aceptan de 1 a 400 productos")
    with LOCK:
        state = load(p)
        if state["state"] != "uploading":
            raise HTTPException(409, "Ya se inició este lote")
        if state["received"] != total:
            raise HTTPException(400, f"Hay {state['received']} pares cargados, se esperaban {total}")
        state.update(state="queued", total=total)
        write(p, state)
    threading.Thread(target=worker, args=(p, total), daemon=True).start()
    return {"state": "queued"}


@app.get("/api/jobs/{job}")
def status(job: str, x_app_key: str | None = Header(None)):
    auth(x_app_key)
    return load(directory(job))


@app.get("/api/jobs/{job}/download")
def download(job: str, x_app_key: str | None = Header(None)):
    # Browser download uses header by fetch() + blob so secret never sits in the URL.
    auth(x_app_key)
    p = directory(job)
    if load(p)["state"] != "done":
        raise HTTPException(409, "El ZIP todavía no está preparado")
    return FileResponse(p / "catalogo_casa_economia.zip", filename=f"catalogo_casa_economia_{job[:8]}.zip", media_type="application/zip")
