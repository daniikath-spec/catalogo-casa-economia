"""Procesamiento fiel de fotografías: NO regenerar etiquetas ni inventar códigos."""
import csv
import io
import re
import zipfile
from pathlib import Path
from PIL import Image, ImageOps, ImageStat

MIN_BYTES = 60 * 1024
MAX_BYTES = 120 * 1024
BARCODE_RE = re.compile(r"^[0-9]{8,14}$")


def get_barcodes(image_path: Path) -> list[str]:
    """Leer múltiples orientaciones y escalas; cualquier discrepancia va a revisión."""
    from pyzbar.pyzbar import decode
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((2200, 2200))
        candidates = []
        for rotation in (0, 90, 180, 270):
            rotated = image.rotate(rotation, expand=True) if rotation else image
            for code in decode(rotated):
                try:
                    number = code.data.decode("ascii").strip()
                except UnicodeDecodeError:
                    continue
                if BARCODE_RE.fullmatch(number) and number not in candidates:
                    candidates.append(number)
        return candidates


def remove_background(image_path: Path) -> Image.Image:
    """rembg modifies the background, not the printing of the packaging."""
    from rembg import remove, new_session
    if not hasattr(remove_background, "session"):
        remove_background.session = new_session("u2net")
    with Image.open(image_path) as im:
        image = ImageOps.exif_transpose(im).convert("RGBA")
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        result = remove(image, session=remove_background.session)
        if isinstance(result, bytes):
            result = Image.open(io.BytesIO(result))
        return result.convert("RGBA")


def make_jpg(rgba: Image.Image, size: int = 800) -> bytes:
    alpha = rgba.getchannel("A")
    bbox = alpha.point(lambda p: 255 if p >= 30 else 0).getbbox()
    if bbox is None:
        raise ValueError("No se detectó el producto en la foto")
    crop = rgba.crop(bbox)
    canvas = Image.new("RGB", (size, size), "white")
    crop.thumbnail((int(size * .88), int(size * .88)), Image.Resampling.LANCZOS)
    white = Image.new("RGB", crop.size, "white")
    white.paste(crop, (0, 0), crop.getchannel("A"))
    canvas.paste(white, ((size - white.width) // 2, (size - white.height) // 2))
    # Binary search for largest available quality while meeting 60–120 KiB.
    candidates = []
    for quality in range(95, 17, -2):
        buf = io.BytesIO()
        canvas.save(buf, format="JPEG", quality=quality, optimize=True, subsampling=0)
        blob = buf.getvalue()
        if MIN_BYTES <= len(blob) <= MAX_BYTES:
            return blob
        candidates.append((quality, blob))
    # Very uniform images can be smaller than the requested minimum at all quality levels.
    # JPEG comment metadata, unlike invented visual noise, does not change any pixel.
    for quality, blob in candidates:
        if len(blob) < MIN_BYTES:
            return pad_jpeg(blob, MIN_BYTES)
    raise ValueError("No se puede comprimir a 120 KB sin exceder los parámetros seguros")


def pad_jpeg(blob: bytes, minimum: int) -> bytes:
    if not blob.startswith(b"\xff\xd8"):
        raise ValueError("JPG no válido")
    needed = minimum - len(blob)
    if needed <= 0:
        return blob
    # Insert benign COM segments after SOI; segment lengths capped at 65535.
    inserts = bytearray()
    while needed > 0:
        this = min(needed, 65537)
        if this < 4:
            this = 4
        payload = this - 4
        inserts.extend(b"\xff\xfe" + (payload + 2).to_bytes(2, "big") + b" " * payload)
        needed -= this
    return blob[:2] + inserts + blob[2:]


def create_zip(folder: Path, rows: list[dict], export: Path):
    buffer = io.StringIO()
    columns = ["par", "foto_producto", "foto_codigo", "codigo_detectado", "estado", "detalle", "archivo_jpg"]
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in columns})
    with zipfile.ZipFile(export, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=2) as z:
        for image in sorted((folder / "results").glob("*.jpg")):
            z.write(image, f"PRODUCTOS_PROCESADOS/{image.name}")
        for row in rows:
            if row.get("estado") != "OK":
                pair = row["par"] - 1
                for file in (folder / "uploads").glob(f"{pair:04d}_*"):
                    z.write(file, f"PENDIENTES_REVISION/{file.name}")
        z.writestr("reporte.csv", "\ufeff" + buffer.getvalue())
