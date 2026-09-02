# CONECCIONES del proyecto GondHawk

Este documento describe la forma en que el frontend puede conectarse con el backend del proyecto para analizar un video desde la interfaz y consumir los resultados generados por el pipeline.

## Estado actual del proyecto

El backend ya genera resultados en `backend/GondHawk/pipeline/output/` mediante el pipeline principal:

- `detecta` personas
- `tracking` por IDs
- `heatmap` por zona
- `tiempo de permanencia`
- `eventos de interacción`
- `metricas_interaccion.json`
- `metricas_pipeline.json`
- `conteo_zonas.json`
- `heatmap.png`

El frontend actual ya cuenta con la capa visual para mostrar métricas y heatmap, pero aún no tiene un servicio real de análisis de video.

---

## Cambios recomendados en backend

### 1. Crear un endpoint para subir un video

Se recomienda agregar un endpoint tipo `POST /api/videos/analyze` o `POST /api/v1/videos/analyze`.

Objetivo:
- recibir el archivo del video subido por el frontend
- validar tipo de archivo
- guardar temporalmente en una carpeta local
- ejecutar el pipeline existente con ese archivo
- devolver la respuesta con las rutas de salida o los datos ya convertidos en JSON

Ejemplo de flujo:

```python
# backend/GondHawk/pipeline/src/api_routes.py
from fastapi import FastAPI, UploadFile, File
from pathlib import Path
import subprocess

app = FastAPI()

@app.post('/api/videos/analyze')
async def analyze_video(file: UploadFile = File(...)):
    upload_dir = Path('backend/GondHawk/pipeline/uploads')
    upload_dir.mkdir(parents=True, exist_ok=True)

    video_path = upload_dir / file.filename
    with video_path.open('wb') as f:
        f.write(await file.read())

    subprocess.run([
        'python',
        'backend/GondHawk/pipeline/src/pipeline.py',
        '--video', str(video_path),
        '--outdir', 'backend/GondHawk/pipeline/output',
    ], check=True)

    return {
        'status': 'ok',
        'video': file.filename,
        'outputs': {
            'metricas_interaccion': 'backend/GondHawk/pipeline/output/metricas_interaccion.json',
            'metricas_pipeline': 'backend/GondHawk/pipeline/output/metricas_pipeline.json',
            'conteo_zonas': 'backend/GondHawk/pipeline/output/conteo_zonas.json',
            'heatmap': 'backend/GondHawk/pipeline/output/heatmap.png',
        }
    }
```

---

### 2. Crear un endpoint para devolver resultados ya procesados

Se recomienda otro endpoint para consultar el último análisis o un análisis concreto.

Ejemplo:

```python
@app.get('/api/videos/latest')
def latest_analysis():
    with open('backend/GondHawk/pipeline/output/metricas_pipeline.json', 'r', encoding='utf-8') as f:
        pipeline = __import__('json').load(f)

    with open('backend/GondHawk/pipeline/output/metricas_interaccion.json', 'r', encoding='utf-8') as f:
        interaction = __import__('json').load(f)

    return {
        'pipeline': pipeline,
        'interaction': interaction,
        'heatmap_url': '/api/videos/heatmap'
    }
```

---

### 3. Crear un endpoint para servir la imagen del heatmap

Este punto es clave para que el front muestre el mapa de calor generado.

```python
@app.get('/api/videos/heatmap')
def heatmap():
    return FileResponse('backend/GondHawk/pipeline/output/heatmap.png')
```

---

## Rutas actuales del proyecto que se pueden usar como base

Estas son rutas reales del repositorio y pueden servir como puntos de conexión:

### Ruta de ejecución del pipeline

```text
backend/GondHawk/pipeline/src/pipeline.py
```

Comando actual de ejemplo:

```bash
python backend/GondHawk/pipeline/src/pipeline.py --video backend/GondHawk/data/vtest.avi
```

### Ruta de salida actual

```text
backend/GondHawk/pipeline/output/
```

Contiene:

```text
backend/GondHawk/pipeline/output/metricas_interaccion.json
backend/GondHawk/pipeline/output/metricas_pipeline.json
backend/GondHawk/pipeline/output/conteo_zonas.json
backend/GondHawk/pipeline/output/heatmap.png
```

### Ruta de frontend donde consumir los endpoints

```text
frontend/src/App.jsx
```

Desde ahí, los fetch podrían quedar así:

```js
const response = await fetch('/api/videos/analyze', {
  method: 'POST',
  body: formData,
});
```

```js
const result = await fetch('/api/videos/latest');
const data = await result.json();
```

```js
const heatmapUrl = '/api/videos/heatmap';
```

---

## Propuesta de contrato JSON para el frontend

### POST /api/videos/analyze

Respuesta esperada:

```json
{
  "status": "ok",
  "video": "demo.mp4",
  "outputs": {
    "metricas_interaccion": "backend/GondHawk/pipeline/output/metricas_interaccion.json",
    "metricas_pipeline": "backend/GondHawk/pipeline/output/metricas_pipeline.json",
    "conteo_zonas": "backend/GondHawk/pipeline/output/conteo_zonas.json",
    "heatmap": "backend/GondHawk/pipeline/output/heatmap.png"
  }
}
```

### GET /api/videos/latest

```json
{
  "pipeline": {
    "pipeline": "GondHawk — Integrante 6 (Laura)",
    "frames_procesados": 795,
    "total_detecciones": 4576,
    "eventos_generados": 104,
    "eventos_compliance": 104
  },
  "interaction": {
    "total": {
      "visitas": 104,
      "tasa_interaccion": 0.0,
      "tasa_rechazo": 0.0
    },
    "zonas": []
  },
  "heatmap_url": "/api/videos/heatmap"
}
```

---

## Recomendación de estructura para implementación

Se sugiere crear una pequeña API dentro del backend con estas rutas:

```text
/api/videos/analyze
/api/videos/latest
/api/videos/heatmap
/api/videos/{id}/metrics
```

Esa estructura hace que el front pueda:
- subir un video,
- lanzar el análisis,
- recuperar resultados y heatmap,
- y mantener una experiencia de dashboard con carga y visualización.

---

## Resumen corto

El backend ya tiene toda la lógica del análisis; lo que falta es una capa de exposición HTTP para que el frontend pueda:

1. enviar un video,
2. ejecutar el pipeline real,
3. leer las métricas generadas,
4. mostrar el heatmap y los KPIs.

La integración es totalmente viable con la estructura actual del proyecto.
