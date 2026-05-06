# Demo Runbook — orden de ejecución (10–12 min)

> Tener abierto **antes** de empezar:
> - **Terminal 1** (PowerShell) en `C:\Users\artox\OneDrive\Desktop\Sistemas Operativos\Proyecto\repo`
> - **Terminal 2** (PowerShell) en el mismo directorio (para correr cosas en paralelo)
> - **Tab Browser 1**: <http://localhost:3000> (dashboard)
> - **Tab Browser 2**: <http://localhost:3001> (Grafana, login admin/admin si pide)
> - **Tab Browser 3**: <http://localhost:8000/docs> (Swagger UI)
> - **Tab Browser 4**: <https://github.com/DylanunGOD/Operating-Systems-Project/pull/14>
>
> Todos los comandos son copy-paste — los números entre `« »` son la
> referencia a quien hizo qué. Léelos en voz alta.

---

## Paso 0 — Pre-flight (hacer 5 min antes de empezar)

```powershell
docker compose ps
curl.exe -s http://localhost:8000/health
curl.exe -s http://localhost:8000/workers
```

**Deberías ver:** 11 contenedores `running`, `{"status":"healthy"...}`, y 3 workers `idle`.
Si algo no responde:

```powershell
docker compose down -v
docker compose up -d
# Esperá ~30 s; volvé a correr el health check
```

> Decir mientras se levanta: "el sistema son **11 contenedores** —
> coordinator FastAPI, 3 workers Python+ffmpeg, Postgres, Redis, dashboard
> React, Prometheus, Grafana, Loki + Promtail. La parte de **Dylan** fue
> el scaffold inicial de coordinator/worker/compose; la **mía** fue
> agregar la capa de observabilidad y los tests; la de **Ian** fue
> conectar el dashboard al stream real-time y agregar el ChaosPanel."

---

## Paso 1 — Health del sistema (40 s)

```powershell
curl.exe -s http://localhost:8000/health
curl.exe -s http://localhost:8000/workers
```

**Mostrar:** la respuesta JSON, los 3 workers idle.

> «**Yo** monté el endpoint `/health` y la suite de tests del coordinator
> (PR #2 con 39 tests usando `fakeredis` y `aiosqlite`). El endpoint
> `/workers` devuelve también el CPU/RAM por nodo — eso lo metí cuando
> arreglé el bug del 404 en PR #5.»

---

## Paso 2 — Dashboard vacío (30 s)

> Cambiar al **Tab Browser 1** (<http://localhost:3000>).

**Mostrar:** WorkersStatus con 3 workers idle, JobsTable vacía, ChaosPanel disponible. La barra del WebSocket dice `connected`.

> «El dashboard vivo es un push: cero polling. **Mi** WebSocket
> `/ws` (PR #1) hace fan-out con `asyncio.Lock` para evitar bugs de
> mutación durante el broadcast. **Ian** lo conectó del lado del
> frontend con su `RealtimeContext` (PR #13) — los componentes
> `JobsTable` y `WorkersStatus` ya no hacen polling, se suscriben al
> store. El `ChaosPanel` que ven a la derecha también es de Ian.»

---

## Paso 3 — Mandar un job individual (1 min)

> Volver al **Terminal 1**.

```powershell
'{"type":"thumbnail","input_path":"./test_files/video_0001.mp4","priority":"normal","params":{"timestamp":1}}' | Set-Content "$env:TEMP\one-job.json" -Encoding utf8 -NoNewline
curl.exe -s -X POST http://localhost:8000/jobs -H "Content-Type: application/json" --data "@$env:TEMP\one-job.json"
```

**Mostrar:** la respuesta tiene `"status":"queued"` y un `id` UUID.

> Cambiar al **dashboard** y señalar que el job aparece sin recargar.

> «**Dylan** levantó el endpoint `POST /jobs` original. **Yo** corregí
> en PR #14 esta semana un bug que hacía que TODOS los jobs cayeran en
> `failed` — la `docker-compose.yml` de producción montaba un volumen
> Docker vacío en `/media`, así que el worker nunca veía el archivo.
> Ahora ven que el job va de `queued → processing → completed`.»

---

## Paso 4 — Batch de 50 thumbnails con CLI (1.5 min)

```powershell
python client/submit_jobs.py --dir ./test_files --type thumbnail --concurrency 5 --no-progress
```

> Mientras corre (~10 s en realidad, pero el CLI imprime el resumen al
> final), cambiar al **dashboard** y al **Grafana**.

**En el dashboard:** la JobsTable se llena en vivo, los workers cambian a `busy`.

**En Grafana** (Tab Browser 2 → dashboard "Multimedia Distributed"):
queue depth sube en el panel 1; "Jobs by Status" panel 2 se mueve;
worker rate panel 3 muestra throughput por worker.

> «El CLI `submit_jobs.py` es **mío** (PR #8). La concurrencia es
> configurable — esos 5 son simultaneous POST en vuelo, no jobs en
> proceso. Las métricas que ven en Grafana también son **mías**:
> `coordinator_queue_depth`, `coordinator_jobs_total{status}`,
> `coordinator_request_duration_seconds` (PR #6), y todo el stack
> Prometheus + Grafana + Loki está provisionado automáticamente
> (PR #9). El dashboard de Grafana lo ven sin login porque el JSON
> ya está en `infra/grafana/dashboards/main.json`.»

---

## Paso 5 — Logs centralizados con Loki (45 s)

> En **Grafana** → menú lateral → **Explore** → seleccionar fuente
> "Loki" → query:

```
{container="worker-1"}
```

**Mostrar:** logs estructurados del worker-1 con los `Picked job from`,
`Processing job ...`, `Job completed`.

> «Loki + Promtail los conecté en PR #9. El Promtail montea
> `/var/lib/docker/containers` y manda los logs JSON-decodificados a
> Loki. Es el centralizado de logs del rubro de monitoreo — no hay que
> hacer `docker logs` a 11 contenedores.»

---

## Paso 6 — Cola con prioridades (2 min) ⭐

> Volver al **Terminal 1**. Mandamos **al revés**: low primero, normal
> después, high al último — y demostramos que los `high` salen
> primero.

```powershell
python client/submit_jobs.py --dir ./test_files --type thumbnail --priority low    --concurrency 5 --no-progress
python client/submit_jobs.py --dir ./test_files --type thumbnail --priority normal --concurrency 5 --no-progress
python client/submit_jobs.py --dir ./test_files --type thumbnail --priority high   --concurrency 5 --no-progress
```

**Mostrar en dashboard:** los jobs con prioridad alta llegan a
`completed` antes que los `normal`, y los `low` últimos.

```powershell
curl.exe -s "http://localhost:8000/jobs?status=completed&limit=5" | python -c "import sys,json; [print(j['priority'], j['completed_at']) for j in json.load(sys.stdin)['jobs']]"
```

> «La cola con prioridades es **de Ian** (PR #13). Son tres listas
> Redis: `jobs:queue:high`, `:normal`, `:low`. Los workers hacen
> `BLPOP queue:high queue:normal queue:low 0` — Redis devuelve del
> primer key no vacío en una sola round-trip, así que tenemos
> *strict priority* sin código de scheduler. En el `LOAD_TEST_REPORT.md`
> medí que los `high` finalizan en mediana **2.74 s** antes que los
> `low` aunque manden los `low` primero.»

---

## Paso 7 — Chaos engineering en vivo (1.5 min) ⭐

> Cambiar al **dashboard** (Tab Browser 1). Hacer scroll hasta el
> **ChaosPanel** y hacer click en `worker_overload`.

**Mostrar:**
- En el panel de chaos: el run aparece con un timer activo.
- El queue depth sube de golpe (30 jobs sintéticos).
- Los workers salen `offline` (visible en WorkersStatus).
- En Grafana, la curva de queue depth tiene un pico.

> «El backend del chaos runner es **mío** (PR #7) — corre en `asyncio`
> al lado del coordinator, ejecuta acciones programadas (`spike_queue`,
> `kill_worker`, `redis_disconnect`, `inject_errors`, `slow_job`) y se
> puede cancelar en cualquier momento con `DELETE /chaos/runs/{id}`.
> El `ChaosPanel` que ven con el botón de cancelar es **de Ian**
> (PR #13). El `worker_overload` que disparé inyecta 30 jobs y marca
> dos workers offline a los 10 s — es la única forma legítima del
> proyecto de simular un fallo distribuido sin tener que matar
> contenedores a mano.»

---

## Paso 8 — Endpoint formal de descarga (45 s)

> Volver al **Terminal 1**.

```powershell
$jobId = curl.exe -s "http://localhost:8000/jobs?status=completed&limit=1" | python -c "import sys,json; print(json.load(sys.stdin)['jobs'][0]['id'])"
Write-Output "Descargando resultado del job $jobId"
curl.exe -OJ "http://localhost:8000/jobs/$jobId/result"
ls *.jpg | Select-Object -Last 1
```

**Mostrar:** un JPG descargado al directorio actual con el UUID del
job en el nombre.

> «`GET /jobs/{id}/result` lo agregó **Ian** en PR #13 — devuelve
> `FileResponse` desde el `output_path`, con 409 si el job no terminó
> y 410 si el archivo desapareció del volumen. Es el entregable
> formal del rubro 2.2 de gestión de archivos.»

---

## Paso 9 — Tests + CI verde (1 min)

> En el **Terminal 2** (para que no interrumpa el flow del demo):

```powershell
python -m pytest tests/ -q --tb=no
```

**Mostrar:** `94 passed, 6 skipped`.

> Cambiar al **Tab Browser 4** (PR #14 en GitHub):

**Mostrar:** los 7 commits de la PR + los 3 checks verdes (lint, test, build).

> «**Yo** monté la suite completa: 39 tests del coordinator (PR #2),
> 21 tests del worker (PR #10), 6 integration tests opt-in (PR #11),
> y la pipeline de CI verde con ruff + black + pytest + docker build
> (PR #4). PR #14 que ven es el de esta semana: arreglé el bug FAILED,
> el lint que dejaron mal, los archivos `.claude/` que se colaron por
> error, y un bug pre-existente del `Settings` con Pydantic V2.»

---

## Paso 10 — Cierre + LOAD_TEST_REPORT (30 s)

> En el **Tab Browser 4** o un editor, mostrar `LOAD_TEST_REPORT.md`.

**Citar:** la tabla de la sección 3 — el resumen agregado por rúbrica.

> «Todos los números que vieron en pantalla están medidos en
> `LOAD_TEST_REPORT.md` con 5 escenarios: baseline (100 jobs en 7.5 s,
> 13.25 jobs/s), saturación (280 jobs con cola pico de 336),
> caída de worker-2 con 50 jobs convert_video (cero perdidos),
> chaos worker_overload, y prioridades. El throughput sostenido es de
> ~6.84 jobs/s con 3 workers — eso es el punto de saturación medido en
> esta misma máquina.»

---

## Plan B si algo falla

| Síntoma | Comando de rescate |
|---|---|
| Dashboard no conecta WS | F5 en el navegador. Si sigue sin reconectar, `docker compose restart dashboard` |
| `POST /jobs` da error 500 | `docker compose logs coordinator \| Select-Object -Last 30` |
| Workers no toman jobs | `docker compose restart worker-1 worker-2 worker-3`; esperar 5 s |
| Grafana pide login | `admin / admin`; si no funciona, `docker compose restart grafana` |
| El batch tarda demasiado | bajar `--concurrency` a 3 |
| Chaos no responde | `curl.exe -s http://localhost:8000/chaos/runs` para ver runs activos; `DELETE /chaos/runs/{id}` para limpiar |
| Todo está muy roto | `docker compose down -v && docker compose up -d` (≈ 30 s para volver) |

---

## Quién hizo qué — referencia rápida para el Q&A

| Componente | Autor | Evidencia |
|---|---|---|
| Coordinator FastAPI base + endpoints `/jobs`, `/workers` | Dylan | scaffold inicial sin PR# |
| Worker base + ffmpeg integration | Dylan | scaffold inicial sin PR# |
| Dashboard React + Vite layout | Dylan | scaffold inicial sin PR# |
| docker-compose original (con bug del volumen) | Dylan | scaffold inicial |
| WebSocket `/ws` + pub/sub fanout | **Artox** | PR #1 |
| Tests del coordinator (39) | **Artox** | PR #2 |
| CI green (ruff + black + pytest + build) | **Artox** | PR #4 |
| Fix 404 workers | **Artox** | PR #5 |
| Métricas Prometheus coordinator + worker | **Artox** | PR #6 |
| Chaos backend (`/chaos/*` runner) | **Artox** | PR #7 |
| Client CLI (submit_jobs + generate_test_files) | **Artox** | PR #8 |
| Stack Prometheus + Grafana + Loki + Promtail | **Artox** | PR #9 |
| Tests del worker (21) | **Artox** | PR #10 |
| Tests de integración E2E | **Artox** | PR #11 |
| Docs README + ARCHITECTURE + DEMO | **Artox** | PR #12 |
| Bind-mount fix del bug FAILED + cleanups + load test report | **Artox** | PR #14 |
| Dashboard real-time refactor (RealtimeContext) | Ian | PR #13 |
| ChaosPanel UI | Ian | PR #13 |
| `auto_generator.py` (generación automática) | Ian | PR #13 |
| Job model: campo `priority` + multi-list Redis | Ian | PR #13 |
| Task types `extract_metadata` + `classify_output` | Ian | PR #13 |
| `GET /jobs/{id}/result` endpoint | Ian | PR #13 |
| `USER_MANUAL.md`, `LOAD_TEST_REPORT.md` (template), `TESTING.md` | Ian | PR #13 |
| Compliance audit (`COMPLIANCE_ANALYSIS.md`) | Ian | PR #13 |
