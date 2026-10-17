# gen_edit_image_ai

Generador y editor de imágenes **100 % local** con Stable Diffusion en tu propia GPU. Escribe un prompt y, si quieres, sube una imagen de referencia o reutiliza una que ya hayas generado: el modelo crea una imagen nueva a partir de ella (imagen→imagen). Todo queda guardado en un historial.

## Qué se construyó

| Servicio | Carpeta | Tecnología | Función |
|----------|---------|------------|---------|
| `frontend` | `front/` + `nginx/` | React 18 + Vite, servido por nginx | Interfaz web. nginx hace de proxy de `/api` hacia el backend |
| `backend` | `back/` | Python 3 + FastAPI + [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) con CUDA | Recibe prompt y referencia, encola la generación y ejecuta `sd-cli` en la GPU |
| `postgres` | — | PostgreSQL 16 | Historial: prompt, parámetros, semilla, rutas de la referencia y del resultado |

```
 navegador ──▶ frontend (nginx) :3010 ──/api──▶ backend (FastAPI + sd-cli, GPU) :8010 ──▶ postgres :5434
               192.168.89.12                     192.168.89.11                          192.168.89.13
                                    red gen-ai-net 192.168.89.0/24
```

### Estructura

```
.
├── back/                 API FastAPI + Dockerfile (compila stable-diffusion.cpp con CUDA)
│   └── app/
│       ├── main.py       endpoints, cola de generación, gestión de archivos
│       ├── sd.py         ejecución de sd-cli y lectura del progreso
│       └── db.py         conexión y esquema de PostgreSQL
├── front/                React + Vite (se compila dentro de la imagen de nginx)
│   └── src/App.jsx       formulario, visor e historial
├── nginx/default.conf    sirve el front y hace de proxy de /api
├── models/               modelos de Stable Diffusion (no se suben al repo)
├── images/
│   ├── generados/        imágenes generadas
│   └── referencia/       imágenes de referencia subidas
└── docker-compose.yml
```

### Funciones del front

- Prompt, prompt negativo, modelo (cualquiera que pongas en `./models`), proporción, pasos, CFG y semilla.
- **Imagen de referencia opcional**: arrástrala o elígela. Con el control *Fuerza de cambio* decides cuánto se aleja de ella. Con referencia se usa la proporción de la imagen.
- **Trabajar sobre una imagen generada**: botón *Usar como referencia* en cualquier resultado del historial.
- Progreso en vivo (paso actual / total) mientras se genera.
- Historial con *Reutilizar parámetros*, *Descargar*, *Eliminar* (una a una) y *Borrar todo*.

## Requisitos

- Docker con Docker Compose
- GPU NVIDIA y [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/)
- Un modelo Stable Diffusion 1.5 en `./models`, por ejemplo [DreamShaper 8](https://huggingface.co/Lykon/DreamShaper) (`DreamShaper_8_pruned.safetensors`). Formatos aceptados: `.safetensors`, `.ckpt`, `.gguf`.

Por defecto se compila para la arquitectura CUDA `75` (GTX 16xx / RTX 20xx). Para otra GPU, cambia `CUDA_ARCH` en `back/Dockerfile` (por ejemplo `86` para RTX 30xx o `89` para RTX 40xx).

## Puesta en marcha

1. Crea un archivo `.env` junto a `docker-compose.yml`:

   ```env
   DB_NAME=genai
   PG_USER=genai
   PG_PASSWORD=una-contraseña-segura
   FRONTEND_PORT=3010
   BACKEND_PORT=8010
   POSTGRES_PORT=5434
   ```

2. Copia tu modelo a `./models`.
3. Levanta todo:

   ```bash
   docker compose up -d --build
   ```

4. Abre http://localhost:3010

La primera construcción del backend tarda varios minutos, porque compila stable-diffusion.cpp con CUDA.

## Persistencia

| En el host | En el contenedor | Contenido |
|------------|------------------|-----------|
| `./models` | `/models` (solo lectura) | Modelos |
| `./images/generados` | `/images/generados` | Imágenes generadas |
| `./images/referencia` | `/images/referencia` | Referencias subidas (normalizadas a PNG) |
| volumen `gen-ai-postgres-data` | `/var/lib/postgresql/data` | Base de datos; sobrevive a `docker compose down` |

Las rutas que se guardan en la base de datos (`/images/generados/...`) corresponden a `./images/generados/...` en el host. Al borrar una generación también se borran sus archivos, salvo que otra generación los use como referencia.

## Tabla `generations`

| Campo | Descripción |
|-------|-------------|
| `prompt`, `negative_prompt` | Texto usado |
| `model`, `width`, `height`, `steps`, `cfg_scale`, `seed`, `sampler` | Parámetros. Se guarda la semilla real, aunque se haya pedido una aleatoria |
| `strength` | Fuerza de cambio (solo con referencia) |
| `reference_path` | Archivo de referencia en el volumen |
| `parent_id` | Generación de la que salió la referencia, si se trabajó sobre una imagen ya generada |
| `output_path` | Imagen generada |
| `status`, `error`, `duration_ms` | Estado (`queued`, `running`, `done`, `error`), error y tiempo de generación |

## API

El backend también se puede usar directamente en `http://localhost:8010`; la documentación interactiva está en `/docs`.

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/models` | Modelos disponibles en `./models` |
| `POST` | `/api/generate` | Encola una generación (multipart: `prompt`, `negative_prompt`, `model`, `aspect`, `steps`, `cfg_scale`, `seed`, `strength`, `reference` (archivo) o `reference_id`) |
| `GET` | `/api/generations` | Historial |
| `GET` | `/api/generations/{id}` | Estado y progreso de una generación |
| `DELETE` | `/api/generations/{id}` | Elimina una generación y sus archivos |
| `DELETE` | `/api/generations` | Elimina todo el historial |
| `GET` | `/api/files/...` | Imágenes de `./images` |

Las generaciones se procesan de una en una, porque hay una sola GPU.

## Créditos

- [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) (MIT): motor de inferencia. Se descarga y compila al construir la imagen del backend; no se incluye en este repositorio.
- Los modelos tienen sus propias licencias y no se distribuyen con este proyecto.
