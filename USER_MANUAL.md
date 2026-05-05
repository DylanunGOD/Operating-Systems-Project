# Manual de usuario — Multimedia Distributed

Este manual está dirigido al **usuario final** del sistema (no al
desarrollador). Si buscas detalles de arquitectura o decisiones de diseño,
consulta `ARCHITECTURE.md`.

## 1. ¿Qué hace el sistema?

Multimedia Distributed es una plataforma para procesar archivos de audio y
video de forma **distribuida y paralela**. Tú envías un lote de archivos al
coordinador; el coordinador los reparte entre tres workers que ejecutan la
operación que pediste (convertir formato, extraer audio, generar
miniaturas, leer metadatos o clasificar resultados). Mientras tanto un
panel web te muestra en tiempo real qué está procesando cada worker, cuánto
falta y si algo falló.

---

## 2. Cómo levantar el sistema

Necesitas Docker Desktop instalado y al menos 4 GB de RAM libres.

```bash
# 1. Clona el repo y entra en la carpeta
cd Operating-Systems-Project

# 2. Levanta TODOS los servicios (coordinador, 3 workers, base de datos,
#    Redis, dashboard, Prometheus + Grafana + Loki)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# 3. Verifica que todo esté en pie
docker compose ps
```

Cuando termine, abre estas URLs en el navegador:

| URL | Sirve para |
|---|---|
| http://localhost:3000 | **Dashboard** (lo que vas a usar más) |
| http://localhost:8000/docs | Swagger UI de la API |
| http://localhost:3001 | Grafana (usuario `admin`, contraseña `admin`) |
| http://localhost:9090 | Prometheus (consultas crudas) |
| http://localhost:8080 | Adminer (inspeccionar la base de datos) |
| http://localhost:8081 | Redis Commander (inspeccionar la cola) |

Para apagar todo:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

---

## 3. Preparar el dataset

Si nunca corriste el sistema, genera el dataset de prueba primero. La
opción **completa** produce 420 archivos diversos (mp4 + mkv + webm + mp3 +
wav, varias duraciones) en pocos minutos:

```bash
python client/generate_test_files.py --preset full --clean
```

Quedará un `manifest.json` y un `README.md` en `test_files/` describiendo
qué se generó. Para una prueba rápida usa `--preset small` (30 archivos).

---

## 4. Enviar trabajos

Hay dos formas: manual y automática.

### 4.1 Manual — `submit_jobs.py`

Envía cada archivo de un directorio con la misma operación.

```bash
# Convertir todos los videos del dataset
python client/submit_jobs.py --dir ./test_files --type convert_video

# Extraer audio con prioridad alta y mucha concurrencia
python client/submit_jobs.py --dir ./test_files --type extract_audio \
    --priority high --concurrency 20

# Generar miniaturas en el segundo 2 de cada video
python client/submit_jobs.py --dir ./test_files --type thumbnail \
    --params-json '{"timestamp": 2}'
```

Tipos de tarea disponibles:

| `--type` | Qué hace |
|---|---|
| `convert_video`     | Re-codifica el video al formato destino (default mp4 / h264) |
| `extract_audio`     | Saca el audio como MP3 |
| `thumbnail`         | Genera una imagen en un timestamp |
| `extract_metadata`  | Lee duración / codec / bitrate con `ffprobe` y los guarda |
| `classify_output`   | Mueve/copía un resultado a subcarpetas por formato y duración |

### 4.2 Automática — `auto_generator.py`

Vigila una carpeta y encola automáticamente todo archivo nuevo, usando el
`manifest.json` para decidir qué operación y prioridad aplicar. No requiere
intervención humana mientras corre.

```bash
# Vigila ./test_files y procesa archivos nuevos cada 10 segundos
python client/auto_generator.py --watch ./test_files --interval 10

# Una sola pasada (útil en cron / CI)
python client/auto_generator.py --watch ./test_files --once
```

Los archivos ya procesados quedan registrados en `test_files/.processed.log`
para no re-encolarlos en pasadas siguientes.

---

## 5. Cómo usar el dashboard

Abre `http://localhost:3000`. Ves cuatro zonas:

```
+------------------------------------------------------------+
|  🎬 Multimedia Distributed              ● En línea         |  ← Estado WS
+------------------------------------------------------------+
|  Cola | Total | Completados | Fallidos | Procesando | ...  |  ← Métricas
+------------------------------------------------------------+
|  ChaosPanel   |   WorkersStatus   |     JobsTable           |
+------------------------------------------------------------+
```

* **Barra superior** — una luz verde indica que el WebSocket está conectado.
  Si parpadea naranja es porque está reintentando.
* **Barra de métricas** — totales agregados en vivo: cuántos jobs hay en
  cola, cuántos workers están idle/busy, etc.
* **WorkersStatus** — lista los 3 workers con CPU, RAM y job actual.
* **JobsTable** — todos los jobs con su estado (`queued` / `processing` /
  `completed` / `failed`), progreso (%) y worker asignado. Filtra por estado
  con el selector de la esquina.
* **ChaosPanel** — botones para lanzar escenarios de chaos (ver §7).

---

## 6. Estados de un job

| Estado       | Color | Qué significa |
|---|---|---|
| `pending`    | amarillo | El coordinador lo aceptó pero aún no lo encoló |
| `queued`     | amarillo | Está en la cola Redis esperando un worker |
| `processing` | azul     | Un worker lo está ejecutando (sigue su barra de progreso) |
| `completed`  | verde    | Terminó bien; el resultado está en el volumen |
| `failed`     | rojo     | Algo salió mal; revisa la columna error en la API |

Para ver el detalle completo de un job:

```bash
curl http://localhost:8000/jobs/<job_id> | jq
```

Para descargar el archivo resultante:

```bash
curl -OJ http://localhost:8000/jobs/<job_id>/result
```

---

## 7. Lanzar escenarios de chaos

El sistema trae cuatro escenarios de prueba predefinidos. Desde el panel
**ChaosPanel** del dashboard:

1. Elige un escenario:
   * **worker_overload** — saturar un worker con jobs simultáneos.
   * **redis_outage** — interrumpir la conexión a Redis.
   * **cascading_failures** — caída en cadena de varios componentes.
   * **slow_network** — agregar latencia a las llamadas internas.
2. Pulsa *Start*.
3. Observa cómo cambian las gráficas y los estados en `JobsTable`.
4. Pulsa *Stop* o espera a que el escenario expire por sí solo.

También se puede disparar por API:

```bash
curl -X POST http://localhost:8000/chaos/runs \
    -H 'Content-Type: application/json' \
    -d '{"scenario_id": "worker_overload"}'
```

---

## 8. Consultar resultados

Tres formas:

* **Por API** — `GET /jobs/{id}/result` devuelve el archivo resultante con
  el nombre original.
* **Por volumen compartido** — los archivos viven en `media_output/` (en el
  host) y `/media/output/` (en los contenedores). Útil si quieres
  inspeccionar muchos a la vez.
* **Vía Adminer** — `http://localhost:8080` te deja correr SQL contra
  Postgres para ver `output_path` y `result_metadata` por job.

---

## 9. Troubleshooting

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| El dashboard no carga | Falta `--build` o el contenedor no levantó | `docker compose ps`, mira logs con `docker compose logs dashboard` |
| Estado del WebSocket en naranja | El coordinador se reinició | Espera 5 s; reconecta solo |
| Todos los jobs fallan apenas se encolan | El worker no ve `/media/input/...` | Revisa que estés levantando con `-f docker-compose.dev.yml` también |
| El job se queda en `queued` para siempre | Cola Redis llena pero ningún worker idle | Revisa `WorkersStatus`; si están todos `busy`, espera o lanza más jobs |
| `ffmpeg: file already exists` en logs | Re-corriste el mismo lote | Ya está arreglado: el coordinador genera nombres con UUID y el worker pasa `-y` |
| Puerto 3000 ocupado | Otro servicio lo está usando | Cierra el otro o cambia `dashboard.ports` en `docker-compose.yml` |
| Puerto 5432 / 6379 ocupado | Tienes Postgres/Redis local corriendo | Detén el local: `sudo systemctl stop postgresql redis` |
| `docker compose down` no borra los datos | Es esperado, hay volúmenes nombrados | Para limpiar todo: `docker compose down -v` |

---

## 10. Comandos útiles

```bash
# Ver logs en vivo de un componente
docker compose logs -f coordinator
docker compose logs -f worker-1

# Ver el contenido de la cola Redis
docker compose exec redis redis-cli LLEN jobs:queue:high
docker compose exec redis redis-cli LRANGE jobs:queue:normal 0 5

# Métricas Prometheus crudas
curl http://localhost:8000/metrics | head -30

# Listar los workers
curl http://localhost:8000/workers | jq

# Resetear toda la base de datos y la cola
docker compose down -v
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```
