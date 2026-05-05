# Análisis de cumplimiento vs enunciado



---

## 1. Cumple

### 1.1 Arquitectura del sistema (rubro 15%)

- Diseño claro de nodos separados: **coordinador**, **3 workers**, **cola Redis**, **PostgreSQL**, **dashboard**, **stack de observabilidad**.
- Redes Docker segmentadas (`backend`, `frontend`, `monitoring`) que hacen explícito el flujo de comunicación.
- Diagrama ASCII en `README.md` y descripción extendida en `ARCHITECTURE.md`.
- Flujo `Cliente → Cola → Coordinador → Workers → Repositorio de resultados → Dashboard` mapea 1:1 con la arquitectura mínima de referencia del enunciado.

**Evidencia:** `README.md`, `ARCHITECTURE.md`, `docker-compose.yml`, `docker-compose.dev.yml`.

### 1.2 Implementación distribuida (rubro 20%)

- 3 workers corriendo en contenedores separados (`worker-1`, `worker-2`, `worker-3`), con IDs únicos y conexiones independientes a Redis y al coordinador.
- Comunicación por red real (TCP a Redis, HTTP al coordinador, WebSocket al dashboard). No hay memoria compartida entre nodos.
- El enunciado permite contenedores como alternativa a máquinas físicas siempre que haya separación real de procesos y comunicación por red — se cumple.
- El coordinador no ejecuta tareas: solo encola y observa. La ejecución es exclusiva de los workers.

**Evidencia:** `docker-compose.yml` (servicios `worker-1/2/3`), `worker/main.py` (BLPOP sobre `jobs:queue`).

### 1.3 Gestión de procesos y concurrencia (rubro 20%)

- **Cola de trabajos:** Redis LIST (`jobs:queue`) con consumo concurrente vía `BLPOP` — múltiples workers compiten por el siguiente job sin condiciones de carrera.
- **Estados del job** implementados: `pending`, `assigned`, `running`, `completed`, `failed`. Coinciden exactamente con los estados exigidos por el enunciado.
- **Asincronía:** el worker publica progreso en un canal pub/sub de Redis (`jobs:progress`), el coordinador lo normaliza y lo reenvía por WebSocket (`/ws`) al dashboard. Los clientes no bloquean esperando el resultado.
- **Heartbeat del sistema:** el coordinador emite un `queue_snapshot` cada 5s con contadores agregados (queue length, workers online/idle/busy).
- **Información por tarea** (enunciado): identificador, archivo asociado, operación, estado, worker responsable, progreso, tiempo de inicio/fin — todos presentes en el modelo `Job` (`coordinator/models/job.py`).

**Evidencia:** `coordinator/models/job.py`, `coordinator/api/routes/jobs.py`, `worker/main.py`, `worker/processor/reporter.py`.

### 1.4 Monitoreo de recursos (rubro 15%)

- Stack completo provisionado en `infra/`: **Prometheus + Grafana + Loki + Promtail**.
- Coordinador expone `/metrics` (queue depth, jobs por estado, latencia p95 de requests).
- Cada worker expone métricas en el puerto `9100` (jobs procesados, duración de job, CPU/memoria).
- Dashboard de Grafana pre-provisionado (`infra/grafana/dashboards/main.json`) con 5 paneles clave.
- Endpoint REST `GET /workers` con CPU y RAM per-worker para la UI.
- Logs estructurados centralizados en Loki y visualizables en Grafana por contenedor.

**Evidencia:** `infra/`, `coordinator/api/routes/workers.py`, `worker/metrics.py`.

### 1.5 Coordinador / Planificador

Responsabilidades del enunciado vs implementación:

| Responsabilidad | Estado | Endpoint / módulo |
|---|---|---|
| Recibir solicitudes de procesamiento | ✅ | `POST /jobs` |
| Registrar trabajos | ✅ | Persistencia en Postgres (`jobs` table) |
| Consultar la cola de tareas | ✅ | `GET /jobs`, Redis LIST |
| Asignar tareas a workers | ✅ | BLPOP (pull-based, natural load balancing) |
| Monitorear estado del sistema | ✅ | `/metrics`, `/workers`, `queue_snapshot` |
| Redistribuir carga | ⚠️ | Parcial — hay retry en fallos y el chaos runner permite simular offline, pero no hay rebalancing activo más allá del pull-model |

### 1.6 Cliente / generador de carga

- `client/submit_jobs.py`: envío concurrente configurable vía `--concurrency`.
- `client/generate_test_files.py`: genera archivos de video sintéticos vía ffmpeg para pruebas.
- `client/test_client.py`: consultas de estado y resultados.
- Consume la API REST pública del coordinador, no accede directamente a Redis ni a Postgres.

**Evidencia:** `client/`.

### 1.7 Dashboard / consola de observación

- React 18 + Vite, corre en `:3000`.
- WebSocket en vivo (`/ws`) con reconexión automática y backoff exponencial.
- Vistas implementadas:
  - **JobsTable** — tabla de jobs con estado, progreso, worker, timestamps.
  - **WorkersStatus** — lista de workers con CPU/RAM/estado.
  - **ChaosPanel** — lanzar/cancelar escenarios de chaos y ver historial.
- Cumple con el rubro del enunciado (visualización del estado del sistema, nodos activos, trabajos pendientes/en proceso/completados/fallidos, comportamiento de carga).

**Evidencia:** `dashboard/src/`.

### 1.8 Documentación técnica

- `README.md` — overview, arquitectura, quick start.
- `ARCHITECTURE.md` — detalle técnico de cada componente y decisiones de diseño.
- `DEMO.md` — guión de demo paso a paso.
- `TESTING.md` — cómo correr la suite de tests.
- Swagger UI autogenerado en `/docs` para la API del coordinador.

### 1.9 Extras que no exige el enunciado pero suman

- **CI en GitHub Actions:** ruff + black + pytest con servicios de Postgres y Redis.
- **~90 tests** (84 unitarios + 6 de integración opt-in).
- **Chaos Engineering:** 4 escenarios (`worker_overload`, `redis_outage`, `cascading_failures`, `slow_network`) con API REST dedicada (`/chaos/*`).
- **Health checks** en todos los contenedores con dependencias explícitas en compose.
- **WebSocket con contrato normalizado** (`event` → `type`, `error_msg` → `error`) para desacoplar el formato interno del cliente web.

---

## 2. Cumple parcialmente

### 2.1 Procesamiento multimedia distribuido (rubro 10%)

**Implementado:**
- `convert_video` — conversión de formato vía ffmpeg con parseo de progreso.
- `extract_audio` — extracción de audio desde video.
- `thumbnail` — generación de miniatura/portada.

**No implementado (el enunciado lista 6 operaciones):**
- Consulta o asociación de metadatos (ej. leer tags ID3, ffprobe + almacenar en DB).
- Integración de letras o recursos informativos asociados.
- Clasificación, organización o preparación de archivos resultantes.

**Impacto:** el enunciado dice "una o varias tareas" → con 3 cumple el mínimo, pero este rubro evalúa profundidad. Con solo operaciones ffmpeg clásicas difícilmente se llega a 5.

**Recomendación:**
1. Agregar un task type `extract_metadata` usando `ffprobe` que guarde `duration`, `codec`, `bitrate`, `resolution` en una nueva tabla `job_metadata` (o en `jobs.result_metadata JSONB`).
2. Agregar un task type `classify_output` que mueva los resultados a subcarpetas por tipo/formato/duración (ej. `media_output/by_format/mp4/`, `by_duration/short/`).
3. Documentar cada tarea en `ARCHITECTURE.md` con su diagrama de flujo individual.

### 2.2 Gestión de archivos y resultados (rubro 10%)

**Implementado:**
- Volumen compartido `media_output/` montado en coordinador y workers.
- Cada job tiene un `output_path` persistido que apunta al archivo resultante.
- Los workers escriben al volumen compartido y el coordinador puede listarlo.

**Falta:**
- **Justificación explícita** del mecanismo elegido (el enunciado exige que cada equipo "defina y justifique" el mecanismo). Hoy está implícito en `ARCHITECTURE.md` pero no hay una sección "Decisión: volumen compartido local" con trade-offs vs alternativas (object storage, DB blobs, sistema de archivos distribuido).
- **Endpoint de descarga**: no hay un `GET /jobs/{id}/result` que sirva el archivo directamente. El cliente debe conocer la ruta en el volumen. El enunciado pide "permitir su descarga o consulta posterior".
- **Asociación formal** entre job y resultado a nivel API (aunque sí existe en DB vía `output_path`).

**Recomendación:**
1. Agregar `GET /jobs/{id}/result` que haga `FileResponse` del archivo resuelto desde `output_path`, con validación de que el job esté `completed`.
2. Agregar sección "Repositorio de resultados" en `ARCHITECTURE.md` comparando las 4 alternativas del enunciado (local compartido / nube / carpeta distribuida / DB) y justificando la elección.

### 2.3 Generación automática de tareas

**Implementado:** cliente manual con concurrencia (`client/submit_jobs.py --dir ./test_files --type convert_video --concurrency 5`).

**Falta:** el enunciado distingue explícitamente **dos mecanismos**:
1. Generación manual ✅
2. **Generación automática**: un proceso que analice una carpeta + metadatos JSON/DB y encole las tareas automáticamente sin intervención humana.

El submit actual requiere invocación manual. No hay un watcher de carpeta ni un cron que detecte nuevos archivos.

**Recomendación:** agregar `client/auto_generator.py` que:
- Observe una carpeta `incoming/` (con `watchdog` o polling cada N segundos).
- Lea metadatos desde un `manifest.json` con entradas tipo `{"file": "x.mp4", "operation": "convert_video", "priority": "high"}`.
- Encole automáticamente vía `POST /jobs`.
- Marque los archivos ya procesados (mover a `processed/` o escribir en `.processed.log`).

---

## 3. No cumple

### 3.1 Dataset multimedia de prueba (crítico)

Este es el gap **más grande** del proyecto y afecta varios rubros a la vez (implementación distribuida, concurrencia, procesamiento multimedia, informe de pruebas).

**Exigido por el enunciado:**
- Entre **400 y 600 archivos** multimedia como mínimo.
- Mezcla de audio **y** video.
- Diversidad de formatos: `mp3`, `wav`, `mp4`, `mkv`, etc.
- Diversidad de tamaños (liviano / mediano / pesado).
- Metadatos asociados vía JSON, base de datos u otra estructura equivalente.
- Documentación de composición, criterios de selección y volumen total.

**Estado actual:**
- **30 archivos** en `test_files/`.
- **Todos `.mp4`**, sin audio puro.
- Sin metadatos asociados (no hay `manifest.json`, no hay tabla de metadatos).
- Sin documentación de criterios.
- Son archivos sintéticos generados por `generate_test_files.py`, no un dataset curado.

**Impacto en rúbrica:**
- Sin un dataset grande no se puede evidenciar **saturación** ni **redistribución de carga** (lo exige el rubro de monitoreo).
- Sin diversidad de formatos, las métricas de procesamiento multimedia son triviales.
- Sin metadatos, la generación automática de tareas (§2.3) no se puede demostrar.

**Recomendación:**
1. Generar 400+ archivos con diversidad real:
   - 150 videos en `.mp4`, 80 en `.mkv`, 40 en `.webm`.
   - 100 audios en `.mp3`, 50 en `.wav`.
   - Tamaños variados (3s, 30s, 2min) y resoluciones mezcladas.
2. Escribir `test_files/manifest.json` con metadatos por archivo (duración teórica, operación sugerida, prioridad).
3. Crear `test_files/README.md` documentando composición, criterios y volumen total (tamaño en MB, distribución por formato).
4. Ajustar `generate_test_files.py` para poder regenerar el dataset completo desde cero de forma reproducible.

### 3.2 Prioridad de trabajos

**Exigido:**
- La cola debe "mantener orden o prioridades".
- El cliente puede indicar "prioridad o configuración del trabajo".

**Estado actual:**
- Redis LIST con FIFO simple vía `RPUSH` + `BLPOP`.
- No hay campo `priority` en el modelo `Job`.
- No hay lógica de priorización en el scheduler.

**Recomendación:**
1. Agregar `priority: str` (`low` / `normal` / `high`) al modelo `Job` y al schema de `POST /jobs`.
2. Reemplazar la LIST única por **3 listas Redis** (`jobs:queue:high`, `:normal`, `:low`) y que el worker haga `BLPOP` con las 3 claves en orden de prioridad: `BLPOP queue:high queue:normal queue:low 0`.
3. Exponer en el dashboard la distribución de jobs pendientes por prioridad.
4. Documentar la decisión en `ARCHITECTURE.md` (por qué multi-list en vez de sorted set o Redis Streams).

### 3.3 Informe de pruebas con evidencia de carga

**Exigido explícitamente como entregable:** "informe de pruebas con evidencia de carga, distribución y comportamiento del sistema".

**Estado actual:**
- `TESTING.md` describe cómo correr la suite automática.
- Suite de `pytest` con 90 tests.
- **No existe** un informe que muestre:
  - Throughput con N workers bajo carga real.
  - Tiempos medios de procesamiento por tipo de tarea.
  - Cómo cambia la distribución entre workers cuando uno falla.
  - Comportamiento ante saturación (cola creciente, backpressure).
  - Capturas/exports de Grafana.

**Recomendación:** crear `LOAD_TEST_REPORT.md` con:
1. **Setup**: versión del sistema, recursos de la máquina, versión de Docker.
2. **Escenarios**:
   - Baseline (100 jobs, 3 workers, sin chaos).
   - Saturación (500 jobs de un tirón).
   - Caída de worker (matar worker-2 en medio de la carga).
   - Chaos `worker_overload` y `cascading_failures`.
3. **Métricas** por escenario:
   - Tiempo total de procesamiento.
   - Jobs completados/fallidos/reintentados.
   - Tiempo promedio por job y p95.
   - Distribución real de carga entre workers (gráfico de barras).
   - Picos de CPU/RAM por worker.
4. **Evidencia visual**: screenshots de Grafana para cada escenario.
5. **Conclusiones**: dónde satura el sistema, dónde escala bien, qué arreglar.

### 3.4 Distribución en máquinas físicas

**Recomendado (no obligatorio):** 3 computadoras físicas distintas, una por integrante.

**Estado actual:** todo en una máquina vía Docker Compose.

El enunciado acepta contenedores como alternativa **siempre que se justifique**. Hoy no hay una justificación explícita en la documentación.

**Recomendación:** agregar en `ARCHITECTURE.md` una sección "Decisiones de despliegue" que explique:
- Por qué se eligieron contenedores (reproducibilidad, facilidad de CI, portabilidad).
- Qué se pierde vs tres máquinas físicas (no hay latencia de red real, no hay fallos de red reales).
- Cómo el diseño **permite** migrar a múltiples máquinas sin cambios de código (solo cambiar hostnames de Redis/Postgres en `.env`).

Opcionalmente, desplegar un cuarto worker en una VM/instancia gratuita (AWS free tier, Fly.io, Railway) para demostrar que la arquitectura sí escala a hosts distintos.

### 3.5 Manual de usuario separado

**Exigido como entregable independiente de la doc técnica.**

**Estado actual:** README + DEMO cubren partes, pero no hay un `USER_MANUAL.md` dirigido al usuario final del sistema (no al desarrollador).

**Recomendación:** crear `USER_MANUAL.md` con:
1. Qué hace el sistema (1 párrafo en lenguaje no técnico).
2. Cómo levantarlo (copiar/pegar de comandos).
3. Cómo enviar un job desde el CLI (ejemplos concretos).
4. Cómo usar el dashboard (screenshots paso a paso).
5. Cómo consultar resultados.
6. Cómo interpretar los estados de un job.
7. Cómo disparar escenarios de chaos desde la UI.
8. Troubleshooting común (puerto ocupado, worker no conecta, etc.).

---

## 4. Resumen por rúbrica

| Rubro | Peso | Estado | Nota estimada | Principal gap |
|---|---|---|---|---|
| Arquitectura del sistema | 15% | ✅ | 4–5 | Falta justificar decisión de contenedores |
| Implementación distribuida | 20% | ✅ | 4 | Dataset pequeño limita la evidencia |
| Gestión de procesos y concurrencia | 20% | ⚠️ | 3–4 | Sin prioridades en la cola |
| Monitoreo y balanceo de recursos | 15% | ✅ | 5 | — |
| Procesamiento multimedia distribuido | 10% | ⚠️ | 3 | Solo 3 de 6 tareas sugeridas |
| Gestión de archivos y resultados | 10% | ⚠️ | 3 | Sin endpoint de descarga ni justificación |
| Interfaz de usuario / dashboard | 5% | ✅ | 4–5 | — |
| Documentación técnica y manual | 5% | ⚠️ | 3–4 | Falta manual de usuario formal |

**Nota ponderada estimada actual:** ~3.7 / 5 (≈74 / 100).
**Nota alcanzable atacando los gaps críticos:** ~4.5 / 5 (≈90 / 100).

---

## 5. Plan de acción priorizado

Ordenado por **impacto en la nota / esfuerzo**:

### Alto impacto, bajo esfuerzo (hacer primero)

1. **Expandir el dataset a 400+ archivos con diversidad real** → toca 3 rúbricas a la vez.
2. **Agregar endpoint `GET /jobs/{id}/result`** → cierra el rubro 2.2 con ~30 líneas de código.
3. **Escribir `LOAD_TEST_REPORT.md`** con screenshots de Grafana bajo los escenarios de chaos que ya existen → el chaos runner ya está, solo hay que documentar lo que produce.
4. **Escribir `USER_MANUAL.md`** → 1 hora de trabajo, cierra el rubro de documentación.

### Alto impacto, esfuerzo medio

5. **Prioridades en la cola** (multi-list Redis + campo `priority`) → refuerza el rubro de concurrencia (20%).
6. **Generación automática de tareas** (`client/auto_generator.py` + `manifest.json`) → cierra la brecha del enunciado sobre los "dos mecanismos".
7. **Agregar task types `extract_metadata` y `classify_output`** → sube el rubro de procesamiento multimedia.

### Bajo impacto o defensivo

8. **Sección "Decisiones de despliegue"** en `ARCHITECTURE.md` justificando contenedores.
9. **Un worker desplegado en una VM externa** (demostrativo, opcional).

---

## 6. Riesgos para la demo

- Si el docente pide "muéstrame 500 archivos procesándose en vivo", hoy no se puede → prioridad crítica expandir dataset.
- Si el docente pregunta "¿dónde está el manual de usuario?" y se le muestra el README, puede interpretarse como que falta ese entregable específico.
- Si el docente revisa la rúbrica punto por punto, la ausencia de prioridades en la cola es un gap fácil de detectar.
- El chaos runner es un arma de doble filo: si falla durante la demo o produce comportamiento inesperado, resta más de lo que suma. Ensayar los 4 escenarios antes.

---

## 7. Qué NO tocar

Componentes en buen estado; modificarlos ahora introduce riesgo sin ganar nota:

- Stack de observabilidad (Prometheus/Grafana/Loki) — ya está en rúbrica máxima.
- WebSocket + normalización de eventos — funciona y está documentado.
- CI pipeline — verde y estable.
- Suite de tests existente — 90 tests pasando es más que suficiente para el alcance académico.
- Modelo de jobs actual (salvo agregar `priority`) — cambios de schema implican migración y rompen tests.



NOTA IMPORTANTE:
REVISAR CUANDO SE PASAN LOS ARCHIVOS A LOS WORKERS EN VEZ DE DECIR QUE VAN BIEN DICEN QUE VAN FAILED
ENFOCAR EL PROGRAMA PARA QUE NO SEA SOLO PARA 30, SINO PARA 500 ARCHIVOS