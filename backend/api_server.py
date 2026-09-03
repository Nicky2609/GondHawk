from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent
PIPELINE_PATH = ROOT / "pipeline" / "src" / "pipeline.py"
OUTPUT_DIR = ROOT / "pipeline" / "output"
UPLOAD_DIR = ROOT / "pipeline" / "uploads"

app = FastAPI(title="GondHawk API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, fallback: Any | None = None) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


@app.get("/health")
def healthcheck() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "GondHawk API",
        "project_root": str(ROOT),
    }


@app.post("/api/videos/analyze")
async def analyze_video(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Debe subir un archivo de video.")

    suffix = Path(file.filename).suffix.lower()
    allowed = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de archivo no soportado: {suffix}. Usa uno de: {sorted(allowed)}",
        )

    upload_path = UPLOAD_DIR / file.filename
    content = await file.read()
    upload_path.write_bytes(content)

    if not PIPELINE_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"No se encontró el pipeline en {PIPELINE_PATH}",
        )

    process = subprocess.run(
        [
            sys.executable,
            str(PIPELINE_PATH),
            "--video",
            str(upload_path),
            "--outdir",
            str(OUTPUT_DIR),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )

    if process.returncode != 0:
        error_detail = process.stderr.strip() or process.stdout.strip() or "Error ejecutando pipeline."
        raise HTTPException(status_code=500, detail=error_detail)

    metrics = _read_json(OUTPUT_DIR / "metricas_pipeline.json", {})
    interaction = _read_json(OUTPUT_DIR / "metricas_interaccion.json", {})

    return {
        "status": "ok",
        "video": file.filename,
        "outputs": {
            "metricas_interaccion": str(OUTPUT_DIR / "metricas_interaccion.json"),
            "metricas_pipeline": str(OUTPUT_DIR / "metricas_pipeline.json"),
            "conteo_zonas": str(OUTPUT_DIR / "conteo_zonas.json"),
            "heatmap": str(OUTPUT_DIR / "heatmap.png"),
        },
        "pipeline": metrics,
        "interaction": interaction,
        "heatmap_url": "/api/videos/heatmap",
    }


@app.get("/api/videos/latest")
def latest_analysis() -> dict[str, Any]:
    pipeline_data = _read_json(OUTPUT_DIR / "metricas_pipeline.json", {})
    interaction_data = _read_json(OUTPUT_DIR / "metricas_interaccion.json", {})
    conteo_data = _read_json(OUTPUT_DIR / "conteo_zonas.json", {"zonas": []})

    if not pipeline_data and not interaction_data:
        raise HTTPException(
            status_code=404,
            detail="Todavía no hay un análisis generado. Subir un video primero mediante POST /api/videos/analyze",
        )

    return {
        "pipeline": pipeline_data,
        "interaction": interaction_data,
        "conteo_zonas": conteo_data,
        "heatmap_url": "/api/videos/heatmap",
    }


@app.get("/api/videos/heatmap")
def heatmap_status() -> FileResponse:
    heatmap_path = OUTPUT_DIR / "heatmap.png"
    if not heatmap_path.exists():
        raise HTTPException(status_code=404, detail="No existe heatmap.png en la salida del pipeline.")
    return FileResponse(heatmap_path, media_type="image/png")


@app.get("/api/videos/output/{filename}")
def output_file(filename: str) -> FileResponse:
    target = OUTPUT_DIR / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"No existe el archivo {filename} en la salida del pipeline.")
    return FileResponse(target)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=False)
