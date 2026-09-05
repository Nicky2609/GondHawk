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
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from historial import HistorialAnalisis  # noqa: E402
from recomendador import generar_recomendaciones  # noqa: E402
from reportes import EXTENSIONES, generar as generar_reporte  # noqa: E402
PIPELINE_PATH = ROOT / "pipeline" / "src" / "pipeline.py"
OUTPUT_DIR = ROOT / "pipeline" / "output"
UPLOAD_DIR = ROOT / "pipeline" / "uploads"

app = FastAPI(title="GondHawk API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

historial = HistorialAnalisis(OUTPUT_DIR)


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
async def analyze_video(
    file: UploadFile = File(...),
    frame_skip: int = 3,
    zonas_auto: bool = False,
) -> dict[str, Any]:
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
            "--frame-skip",
            str(frame_skip),
        ]
        + (["--zonas-auto"] if zonas_auto else []),
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )

    if process.returncode != 0:
        error_detail = process.stderr.strip() or process.stdout.strip() or "Error ejecutando pipeline."
        # Un video que no es de una superficie comercial es un error del
        # usuario (422), no una falla del servidor (500): el frontend debe
        # poder mostrar "este video no es de góndolas" en vez de "error
        # interno".
        if "VideoNoRetailError" in error_detail:
            raise HTTPException(
                status_code=422,
                detail=(
                    "El video no parece corresponder a una superficie comercial. "
                    "Sube una grabación de góndolas o pasillos de tienda."
                ),
            )
        raise HTTPException(status_code=500, detail=error_detail)

    metrics = _read_json(OUTPUT_DIR / "metricas_pipeline.json", {})
    interaction = _read_json(OUTPUT_DIR / "metricas_interaccion.json", {})

    interaccion_total = (interaction or {}).get("total", {})
    tomas = interaccion_total.get("toma_producto", 0)
    visitas = interaccion_total.get("visitas", 0)

    # El frontend mostraba "El backend no devolvió un mensaje" incluso cuando
    # el análisis salía bien. Ahora siempre viaja un mensaje, y si el embudo
    # quedó en cero se dice POR QUÉ: casi siempre es que las zonas no
    # corresponden a este video.
    if visitas == 0:
        mensaje = (
            "El análisis terminó, pero ninguna persona entró a las zonas "
            "definidas. Las zonas probablemente no corresponden a este video: "
            "vuelve a analizarlo con zonas_auto=true o redefínelas."
        )
    elif tomas == 0:
        mensaje = (
            f"Análisis completo: {visitas} visitas registradas, pero ninguna "
            "toma de producto. Revisa que las zonas cubran los estantes."
        )
    else:
        mensaje = f"Análisis completo: {visitas} visitas y {tomas} tomas de producto."

    resultado = {
        "status": "ok",
        "mensaje": mensaje,
        "video": file.filename,
        "outputs": {
            "metricas_interaccion": str(OUTPUT_DIR / "metricas_interaccion.json"),
            "metricas_pipeline": str(OUTPUT_DIR / "metricas_pipeline.json"),
            "conteo_zonas": str(OUTPUT_DIR / "conteo_zonas.json"),
            "heatmap": str(OUTPUT_DIR / "heatmap.png"),
            "video_anotado": str(OUTPUT_DIR / "video_anotado.mp4"),
        },
        "pipeline": metrics,
        "interaction": interaction,
        "heatmap_url": "/api/videos/heatmap",
    }

    # Se archiva la corrida ANTES de responder, para que el frontend pueda
    # abrir el detalle inmediatamente y para que el próximo análisis no pise
    # estos resultados.
    entrada = historial.registrar(file.filename, resultado)
    resultado["analisis_id"] = entrada["id"]
    resultado["video_anotado_url"] = f"/api/analisis/{entrada['id']}/archivo/video_anotado.mp4"
    resultado["reportes"] = {
        formato: f"/api/analisis/{entrada['id']}/reporte/{formato}"
        for formato in ("pdf", "excel", "word")
    }
    resultado["recomendaciones"] = (interaction or {}).get("recomendaciones", [])
    resultado["heatmap_url"] = f"/api/analisis/{entrada['id']}/archivo/heatmap.png"
    return resultado


# ── Historial ───────────────────────────────────────────────────────────────


@app.get("/api/analisis")
def listar_analisis(limite: int | None = None) -> dict[str, Any]:
    """Lista de análisis, del más reciente al más antiguo."""
    return {
        "analisis": historial.listar(limite),
        "estadisticas": historial.estadisticas(),
    }


@app.get("/api/analisis/{analisis_id}")
def detalle_analisis(analisis_id: str) -> dict[str, Any]:
    detalle = historial.obtener(analisis_id)
    if detalle is None:
        raise HTTPException(status_code=404, detail=f"No existe el análisis {analisis_id}")
    return detalle


@app.get("/api/analisis/{analisis_id}/archivo/{nombre}")
def archivo_analisis(analisis_id: str, nombre: str) -> FileResponse:
    """Sirve un archivo de una corrida guardada (heatmap, video, JSON...)."""
    ruta = historial.ruta_archivo(analisis_id, nombre)
    if ruta is None:
        raise HTTPException(status_code=404, detail=f"No existe {nombre} en {analisis_id}")

    tipos = {
        ".png": "image/png",
        ".mp4": "video/mp4",
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
    }
    return FileResponse(ruta, media_type=tipos.get(ruta.suffix, "application/octet-stream"))


@app.get("/api/analisis/{analisis_id}/reporte/{formato}")
def descargar_reporte(analisis_id: str, formato: str) -> FileResponse:
    """
    Genera y devuelve el reporte del análisis en pdf, excel o word.

    Se genera bajo demanda y no en cada corrida: producir tres documentos por
    video costaría tiempo en un análisis que quizá nadie descargue.
    """
    formato = formato.lower()
    if formato not in EXTENSIONES:
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado: {formato}. Usa pdf, excel o word.",
        )

    carpeta = historial.dir_analisis / analisis_id
    if not carpeta.exists():
        raise HTTPException(status_code=404, detail=f"No existe el análisis {analisis_id}")

    nombre = f"reporte_gondhawk{EXTENSIONES[formato]}"
    destino = carpeta / nombre

    if not destino.exists():
        try:
            generar_reporte(formato, carpeta, destino)
        except ImportError as exc:
            raise HTTPException(
                status_code=501,
                detail=(
                    f"Falta la dependencia para generar {formato}: {exc}. "
                    "Instala: pip install reportlab openpyxl python-docx pillow"
                ),
            ) from None

    tipos = {
        "pdf": "application/pdf",
        "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    return FileResponse(destino, media_type=tipos[formato], filename=nombre)


@app.get("/api/analisis/{analisis_id}/recomendaciones")
def recomendaciones_analisis(analisis_id: str, usar_ia: bool = True) -> dict[str, Any]:
    """Recalcula las recomendaciones de un análisis guardado."""
    ruta = historial.ruta_archivo(analisis_id, "metricas_interaccion.json")
    if ruta is None:
        raise HTTPException(
            status_code=404,
            detail=f"No hay métricas guardadas para el análisis {analisis_id}",
        )
    return generar_recomendaciones(_read_json(ruta, {}), usar_ia=usar_ia)


@app.delete("/api/analisis/{analisis_id}")
def eliminar_analisis(analisis_id: str) -> dict[str, Any]:
    if not historial.eliminar(analisis_id):
        raise HTTPException(status_code=404, detail=f"No existe el análisis {analisis_id}")
    return {"status": "ok", "eliminado": analisis_id}


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
