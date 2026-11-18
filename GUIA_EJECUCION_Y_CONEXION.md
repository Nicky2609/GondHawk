# GondHawk: ejecución y conexión

## Requisitos

- Windows PowerShell / Consola de Visual
- Python 3.11 o compatible
- Node.js y npm
- Dependencias Python instaladas en `.venv`
- Dependencias JavaScript instaladas en `frontend/node_modules`

## Levantar el backend

Desde la raíz del proyecto:

```cmd
.venv\Scripts\Activate.ps1
cd backend
python api_server.py
```

El API queda disponible en:

```text
http://localhost:8000
```

Comprobación de salud:

```powershell
Invoke-WebRequest http://localhost:8000/health
```

Si el entorno virtual todavía no tiene las dependencias entonces ejecutar esto en la raíz:

```cmd
pip install -r backend\pipeline\requirements.txt
pip install fastapi uvicorn python-multipart
```

## Levantar el frontend

Abrir otra terminal y ejecutar desde la carpeta del frontend. La raíz del proyecto no contiene `package.json`.

```powershell
Set-Location .\frontend
npm install
npm run dev -- --host 0.0.0.0
```

La interfaz queda disponible en:

```text
http://localhost:5173
```

El script `npm run dev` ejecuta primero la sincronización de archivos de salida y después inicia Vite. La aplicación visual consume directamente el API local.

## Tecnología del frontend

- React 19 para la composición de la interfaz.
- Vite 8 para desarrollo y compilación.
- JavaScript/JSX.
- Tailwind CSS 4 mediante `@tailwindcss/vite`.
- CSS propio en `frontend/src/index.css` para el tema, layout, navegación y responsive.
- `lucide-react` para iconos.
- Recharts para visualizaciones disponibles en los componentes.

Archivos visuales principales:

- `frontend/src/App.jsx`
- `frontend/src/index.css`
- `frontend/src/components/`

## Comunicación entre frontend y backend

La configuración de las rutas se encuentra en:

```text
frontend/src/config/dataConfig.js
```

La base del API es:

```text
http://localhost:8000
```

### Analizar un video

```http
POST /api/videos/analyze
```

El frontend envía el video como `multipart/form-data`, usando el campo `file`:

```js
const formData = new FormData();
formData.append('file', selectedFile);
```

La solicitud es realizada desde:

```text
frontend/src/App.jsx
```

El backend guarda el archivo, ejecuta el pipeline y devuelve las métricas de la ejecución actual junto con la ruta del heatmap.

### Consultar el último análisis

```http
GET /api/videos/latest
```

Este endpoint devuelve el último resultado guardado por el backend. La interfaz actual inicia vacía y actualiza sus paneles con la respuesta del análisis que se acaba de ejecutar.

### Obtener el heatmap

```http
GET /api/videos/heatmap
```

Devuelve `heatmap.png` generado por el pipeline. El frontend añade un identificador de análisis a la URL para evitar que el navegador reutilice el heatmap anterior.

### Obtener archivos de salida

```http
GET /api/videos/output/{filename}
```

Sirve archivos existentes dentro de `backend/pipeline/output/`.

## Flujo completo

1. El usuario selecciona un video en React.
2. React envía el archivo al endpoint `POST /api/videos/analyze`.
3. FastAPI guarda el video en `backend/pipeline/uploads/`.
4. FastAPI ejecuta `backend/pipeline/src/pipeline.py`.
5. El pipeline genera métricas, eventos, conteos y heatmap en `backend/pipeline/output/`.
6. FastAPI devuelve el resultado JSON.
7. React actualiza KPIs, estado por góndola, embudo, alertas y heatmap.

## Comandos de validación

Frontend:

```powershell
Set-Location .\frontend
npm run build
npm run lint
```

Backend:

```powershell
.\.venv\Scripts\Activate.ps1
python -m py_compile backend\api_server.py
```

Para probar el endpoint con un video:

```powershell
curl.exe -F "file=@C:\ruta\al\video.mp4" http://localhost:8000/api/videos/analyze
```

## Ejecución rápida con Docker

### Archivos de contenedorización

- `.dockerignore`: excluye `node_modules`, `.venv`, `dataset_sintetico` y salidas pesadas del contexto Docker.
- `backend/Dockerfile`: construye el API FastAPI sobre `python:3.11-slim` con PyTorch CPU, OpenCV, FFmpeg y Ultralytics.
- `frontend/Dockerfile`: compila Vite React con `node:20-alpine` y sirve el build en `nginx:alpine`.
- `frontend/nginx.conf`: enruta la aplicación SPA en el puerto 80 del contenedor.
- `frontend/.dockerignore`: excluye `node_modules` y `dist` del contexto frontend.
- `docker-compose.yml`: orquesta `backend` y `frontend` con volúmenes persistentes y healthcheck.

### Requisitos

- Docker Desktop o Docker Engine con Docker Compose v2.

### Levantar los contenedores

Ejecuta el comando en la raíz del repositorio:

```powershell
docker compose up --build -d
```

Verifica el estado de los contenedores:

```powershell
docker compose ps
```

Consulta los logs en tiempo real:

```powershell
docker compose logs -f
```

Accede a los servicios en las rutas locales:

```text
Frontend: http://localhost:5173
Backend API: http://localhost:8000
Documentación OpenAPI: http://localhost:8000/docs
Salud del API: http://localhost:8000/health
```

Detén los contenedores sin borrar los datos generados:

```powershell
docker compose down
```

### Variables opcionales y persistencia

- Crea `backend/.env` o define variables de entorno antes de ejecutar `docker compose up`.
- Variables admitidas: `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_BUCKET`, `GONDHAWK_TIENDA_ID` y `GONDHAWK_CAMARA_ID`.
- Sin credenciales externas, el contenedor guarda resultados en los volúmenes `gondhawk_output` y `gondhawk_uploads`.
- El `backend/Dockerfile` enlaza `runs/detect/train/weights/best.pt` a `last.pt` cuando `last.pt` no existe en el repositorio.
- Para compilar con soporte CUDA, ejecuta el build del backend pasando `--build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124`.

