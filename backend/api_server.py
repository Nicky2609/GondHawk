from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

# Las credenciales de Supabase se leen de backend/.env. Se carga antes de
# importar el almacen, porque este decide contra que persiste al construirse.
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from almacen import crear_historial  # noqa: E402
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

# El historial se elige segun el entorno: Supabase si hay credenciales,
# disco si no. Ver pipeline/src/almacen.py.
historial = crear_historial(OUTPUT_DIR)


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

    # Solo el nombre base, sin directorios: un archivo llamado
    # "../../pipeline/src/pipeline.py" sobrescribiría código del proyecto.
    nombre_seguro = re.sub(r"[^\w.\-]+", "_", Path(file.filename).name) or "video"
    upload_path = UPLOAD_DIR / nombre_seguro
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


# ── Escena sintética 3D ─────────────────────────────────────────────────────

ESCENA3D_PATH = ROOT / "pipeline" / "src" / "escena3d.py"
EVALUADOR_PATH = ROOT / "deteccion_eventos" / "tools" / "evaluar_exactitud.py"


# Trabajos de generación 3D en curso. El render tarda minutos, así que la
# petición HTTP no puede esperarlo: se lanza en un hilo y el cliente consulta
# el estado. Un diccionario en memoria basta — si el servidor se reinicia, un
# trabajo a medias se pierde y se vuelve a lanzar, que es lo aceptable aquí.
TRABAJOS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _actualizar(job_id: str, **campos: Any) -> None:
    with _LOCK:
        if job_id in TRABAJOS:
            TRABAJOS[job_id].update(campos)


@app.post("/api/sintetico/generar")
def generar_escena_sintetica(
    duracion: int = 90,
    personas: int = 14,
    gondolas: int = 3,
    seed: int = 7,
) -> dict[str, Any]:
    """
    Lanza la generación de una escena 3D en segundo plano.

    Devuelve de inmediato un `job_id` con el que consultar el progreso en
    /api/sintetico/estado/{job_id}. El render son unos 3 frames por segundo,
    así que 90 s de video a 15 fps pasan de diez minutos: mantener la conexión
    abierta todo ese tiempo agota el tiempo de espera del navegador y deja al
    usuario sin saber si sigue vivo.
    """
    if not (10 <= duracion <= 180):
        raise HTTPException(status_code=400, detail="La duración debe estar entre 10 y 180 s.")
    if not (2 <= personas <= 30):
        raise HTTPException(status_code=400, detail="Las personas deben estar entre 2 y 30.")
    if not (1 <= gondolas <= 6):
        raise HTTPException(status_code=400, detail="Las góndolas deben estar entre 1 y 6.")
    if not ESCENA3D_PATH.exists():
        raise HTTPException(status_code=500, detail=f"No se encontró {ESCENA3D_PATH}")

    job_id = uuid.uuid4().hex[:12]
    total_frames = duracion * 15
    with _LOCK:
        TRABAJOS[job_id] = {
            "job_id": job_id,
            "estado": "renderizando",
            "etapa": "Generando la escena 3D",
            "progreso": 0.0,
            "iniciado": datetime.now().isoformat(timespec="seconds"),
            "duracion": duracion,
            "personas": personas,
            "gondolas": gondolas,
            "seed": seed,
            "total_frames": total_frames,
            "estimado_s": int(total_frames / 3 + duracion * 1.5),
            "resultado": None,
            "error": None,
        }

    hilo = threading.Thread(
        target=_ejecutar_escena_3d,
        args=(job_id, duracion, personas, gondolas, seed),
        daemon=True,
    )
    hilo.start()

    with _LOCK:
        return dict(TRABAJOS[job_id])


@app.get("/api/sintetico/estado/{job_id}")
def estado_escena_sintetica(job_id: str) -> dict[str, Any]:
    """Progreso de una generación en curso o su resultado si ya terminó."""
    with _LOCK:
        trabajo = TRABAJOS.get(job_id)
        if trabajo is None:
            raise HTTPException(status_code=404, detail=f"No existe el trabajo {job_id}")
        return dict(trabajo)


@app.get("/api/sintetico/trabajos")
def listar_trabajos() -> dict[str, Any]:
    """Trabajos de esta sesión, del más reciente al más antiguo."""
    with _LOCK:
        trabajos = sorted(TRABAJOS.values(), key=lambda t: t["iniciado"], reverse=True)
        return {"trabajos": [dict(t) for t in trabajos]}


def _ejecutar_escena_3d(
    job_id: str, duracion: int, personas: int, gondolas: int, seed: int
) -> None:
    """Render + análisis, en un hilo aparte. Reporta progreso leyendo la salida."""
    nombre = f"escena3d_d{duracion}_p{personas}_g{gondolas}_s{seed}.mp4"
    ruta_video = UPLOAD_DIR / nombre
    base = ruta_video.with_suffix("")
    total_frames = duracion * 15

    try:
        # El generador imprime "[render] frame N/M": se lee esa línea para
        # convertirla en progreso real en vez de una barra indeterminada.
        proceso = subprocess.Popen(
            [
                sys.executable, str(ESCENA3D_PATH),
                "--output", str(ruta_video),
                "--duracion", str(duracion),
                "--personas", str(personas),
                "--gondolas", str(gondolas),
                "--seed", str(seed),
            ],
            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        ultimas = []
        for linea in proceso.stdout:
            ultimas.append(linea.rstrip())
            ultimas = ultimas[-40:]
            if "[render] frame" in linea:
                try:
                    n = int(linea.split("frame")[1].split("/")[0])
                    _actualizar(job_id, progreso=round(0.75 * n / max(1, total_frames), 3))
                except (ValueError, IndexError):
                    pass
        proceso.wait()

        if proceso.returncode != 0:
            _actualizar(
                job_id, estado="error",
                error="\n".join(ultimas[-12:]) or "Error generando la escena 3D.",
            )
            return

        _actualizar(
            job_id, etapa="Analizando con el pipeline", progreso=0.78,
        )

        analisis = subprocess.run(
            [
                sys.executable, str(PIPELINE_PATH),
                "--video", str(ruta_video),
                "--zonas", str(Path(f"{base}_zonas.json")),
                "--outdir", str(OUTPUT_DIR),
                "--frame-skip", "1",
                "--sin-verificar-escena",
            ],
            cwd=str(ROOT), capture_output=True, text=True, timeout=3600,
        )
        if analisis.returncode != 0:
            _actualizar(
                job_id, estado="error",
                error=(analisis.stderr or analisis.stdout).strip()[-800:],
            )
            return

        _actualizar(job_id, etapa="Midiendo exactitud", progreso=0.94)
        resultado = _archivar_escena(nombre, base, duracion, personas)
        _actualizar(
            job_id, estado="listo", etapa="Completado",
            progreso=1.0, resultado=resultado,
        )

    except Exception as exc:  # noqa: BLE001 — el hilo no debe morir en silencio
        _actualizar(job_id, estado="error", error=str(exc))


def _archivar_escena(
    nombre: str, base: Path, duracion: int, personas: int
) -> dict[str, Any]:
    """Empaqueta el resultado y lo guarda en el historial, como cualquier análisis."""
    ruta_gt = Path(f"{base}_ground_truth.json")
    ruta_zonas = Path(f"{base}_zonas.json")

    metrics = _read_json(OUTPUT_DIR / "metricas_pipeline.json", {})
    interaction = _read_json(OUTPUT_DIR / "metricas_interaccion.json", {})
    ground_truth = _read_json(ruta_gt, {})

    resultado = {
        "status": "ok",
        "mensaje": (
            f"Escena 3D generada y analizada: {personas} personas sintéticas en "
            f"{duracion} s. Ninguna persona real fue grabada."
        ),
        "video": nombre,
        "sintetico": True,
        "pipeline": metrics,
        "interaction": interaction,
        "ground_truth": ground_truth.get("meta", {}),
        "eventos_esperados": _contar_eventos_esperados(ground_truth),
    }

    entrada = historial.registrar(nombre, resultado)
    analisis_id = entrada["id"]

    # El ground truth se archiva junto al análisis para poder recalcular la
    # exactitud después sin volver a generar el video.
    carpeta = historial.dir_analisis / analisis_id
    for origen in (ruta_gt, ruta_zonas):
        if origen.exists():
            shutil.copy2(origen, carpeta / origen.name)

    resultado["analisis_id"] = analisis_id
    resultado["heatmap_url"] = f"/api/analisis/{analisis_id}/archivo/heatmap.png"
    resultado["video_anotado_url"] = f"/api/analisis/{analisis_id}/archivo/video_anotado.mp4"
    resultado["reportes"] = {
        formato: f"/api/analisis/{analisis_id}/reporte/{formato}"
        for formato in ("pdf", "excel", "word")
    }
    resultado["exactitud"] = _medir_exactitud(analisis_id, ruta_gt)
    return resultado


def _contar_eventos_esperados(ground_truth: dict) -> dict[str, int]:
    conteo: dict[str, int] = {}
    for persona in ground_truth.get("personas", []):
        for evento in persona.get("eventos_esperados", []):
            tipo = evento.get("event_type")
            conteo[tipo] = conteo.get(tipo, 0) + 1
    return conteo


def _medir_exactitud(analisis_id: str, ruta_gt: Path) -> dict[str, Any] | None:
    """
    Compara los eventos detectados con la verdad de fondo del generador.

    Devuelve None si falta el evaluador o el ground truth: la exactitud es un
    extra, no debe impedir que el análisis se muestre.
    """
    eventos = historial.ruta_archivo(analisis_id, "eventos_interaccion.jsonl")
    if eventos is None or not ruta_gt.exists() or not EVALUADOR_PATH.exists():
        return None

    salida = historial.dir_analisis / analisis_id / "exactitud.json"
    proceso = subprocess.run(
        [
            sys.executable, str(EVALUADOR_PATH),
            "--eventos", str(eventos),
            "--ground-truth", str(ruta_gt),
            "--salida", str(salida),
        ],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    if proceso.returncode != 0 or not salida.exists():
        return None
    return _read_json(salida, None)


@app.get("/api/sintetico/{analisis_id}/exactitud")
def exactitud_sintetico(analisis_id: str) -> dict[str, Any]:
    """Exactitud ya calculada de un análisis sintético guardado."""
    ruta = historial.ruta_archivo(analisis_id, "exactitud.json")
    if ruta is None:
        raise HTTPException(
            status_code=404,
            detail="Este análisis no tiene medición de exactitud (no es sintético).",
        )
    return _read_json(ruta, {})


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
def archivo_analisis(analisis_id: str, nombre: str, request: Request) -> Response:
    """
    Sirve un archivo de una corrida guardada (heatmap, video, JSON...).

    El video necesita soporte real de rangos HTTP: el elemento <video> pide
    trozos con la cabecera Range, y FileResponse responde 206 sin las
    cabeceras Content-Range correctas, así que el navegador corta la conexión
    y el reproductor queda en negro aunque el archivo esté bien codificado.
    """
    ruta = historial.ruta_archivo(analisis_id, nombre)
    if ruta is None:
        raise HTTPException(status_code=404, detail=f"No existe {nombre} en {analisis_id}")

    tipos = {
        ".png": "image/png",
        ".mp4": "video/mp4",
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
    }
    media_type = tipos.get(ruta.suffix, "application/octet-stream")

    if ruta.suffix != ".mp4":
        return FileResponse(ruta, media_type=media_type)

    tamano = ruta.stat().st_size
    rango = request.headers.get("range")

    if not rango:
        return FileResponse(
            ruta,
            media_type=media_type,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(tamano)},
        )

    # Range: bytes=INICIO-FIN  (FIN es opcional)
    try:
        unidades, _, tramo = rango.partition("=")
        if unidades.strip().lower() != "bytes":
            raise ValueError(rango)
        inicio_txt, _, fin_txt = tramo.partition("-")
        inicio = int(inicio_txt) if inicio_txt else 0
        fin = int(fin_txt) if fin_txt else tamano - 1
    except ValueError:
        raise HTTPException(status_code=416, detail="Cabecera Range inválida")

    fin = min(fin, tamano - 1)
    if inicio > fin:
        raise HTTPException(status_code=416, detail="Rango fuera del archivo")

    def leer_tramo():
        # Se envía en trozos de 1 MB: mandar el rango completo de una vez
        # dispara el uso de memoria con videos largos.
        with ruta.open("rb") as fh:
            fh.seek(inicio)
            restante = fin - inicio + 1
            while restante > 0:
                datos = fh.read(min(1024 * 1024, restante))
                if not datos:
                    break
                restante -= len(datos)
                yield datos

    return StreamingResponse(
        leer_tramo(),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {inicio}-{fin}/{tamano}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(fin - inicio + 1),
        },
    )


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


@app.get("/api/analitica/zonas")
def analitica_zonas(limite: int = 50) -> dict[str, Any]:
    """
    Rendimiento historico por gondola, agregado sobre TODOS los analisis.

    Es la consulta que solo se puede responder con base de datos: con el
    historial en disco habria que abrir y sumar cada JSON guardado.
    """
    if not hasattr(historial, "rendimiento_zonas"):
        raise HTTPException(
            status_code=501,
            detail=(
                "La analitica historica requiere Supabase configurado. "
                "Define SUPABASE_URL y SUPABASE_SERVICE_KEY en backend/.env"
            ),
        )
    return {"zonas": historial.rendimiento_zonas(limite)}


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
    # Igual que en el historial: sin esta validación, /api/videos/output/../../
    # sirve cualquier archivo del servidor.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")
    target = OUTPUT_DIR / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"No existe el archivo {filename} en la salida del pipeline.")
    return FileResponse(target)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=False)