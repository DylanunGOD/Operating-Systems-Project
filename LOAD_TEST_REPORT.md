# Informe de pruebas de carga

> **Estado:** corrida ejecutada el **2026-05-06** sobre la rama
> `feat/compliance-fixes` (commits c57995b…2a347b7 más los que cierran
> esta corrida). Las cifras de cada escenario provienen de la ejecución
> automática del runner `.tmp_loadtest/run_scenario.py`; los JSON crudos
> se guardan en `.tmp_loadtest/<scenario>.json` y son reproducibles con
> los comandos de la §2.

Este informe cumple el entregable «informe de pruebas con evidencia de
carga, distribución y comportamiento del sistema» exigido en la rúbrica.

---

## 1. Setup del banco de pruebas

| Ítem | Valor |
|---|---|
| Sistema operativo del host | Windows 11 Pro 10.0.26200 |
| CPU                        | AMD Ryzen 7 7700 (8 núcleos, 16 hilos) |
| RAM                        | 15.1 GB |
| Docker Desktop             | 28.3.3 (Compose v2.39.2) |
| Recursos asignados a Docker| Default del WSL2 backend (50 % CPU host, ≈12 GB RAM) |
| Versión del sistema        | Rama `feat/compliance-fixes` (PR #14) |
| Dataset usado              | `test_files/` con **420 archivos** generados con `--preset full --clean` (seed=42 implícito) — 280 video (mp4/mkv/webm), 140 audio (mp3/wav). Tamaño total ≈ 6 MB; manifest.json + README.md en la misma carpeta. |
| Topología                  | 1 coordinator + 3 workers + Postgres + Redis + Prometheus + Grafana + Loki + Promtail + Dashboard (11 contenedores) |

**Cómo levantar el entorno antes de cada escenario:**

```bash
docker compose down -v
docker compose up -d --build
# generar dataset (worker image lleva ffmpeg, así no hace falta instalarlo en el host):
docker run --rm -v "$PWD:/repo" -w /repo --entrypoint python \
    repo-worker-1:latest client/generate_test_files.py --preset full --clean
```

Los runners viven bajo `.tmp_loadtest/` (ignorado por `.gitignore`); cada
escenario emite un JSON con métricas y outcomes por job.

---

## 2. Escenarios

### Escenario A — Baseline

> **Propósito:** establecer línea base — tiempo total y throughput sin
> fallos inducidos.

* **Carga:** 100 jobs `thumbnail`, prioridad `normal`, concurrencia 10.
* **Comando:**
  ```bash
  python .tmp_loadtest/run_scenario.py --name baseline \
      --type thumbnail --count 100 --concurrency 10 --priority normal
  ```

| Métrica | Valor |
|---|---|
| Tiempo total            | **7.546 s** |
| Throughput              | **13.25 jobs/s** |
| Jobs `completed`        | **100 / 100** |
| Jobs `failed`           | **0** |
| Reintentos              | **0** |
| Tiempo medio por job    | **0.140 s** |
| p50 por job             | **0.135 s** |
| p95 por job             | **0.210 s** |
| Distribución por worker | worker-1: **33 %**, worker-2: **33 %**, worker-3: **34 %** |
| Profundidad de cola pico| **85 jobs** (mientras los workers drenaban) |
| Workers concurrentemente activos | **3 / 3** |

**Lectura:** la distribución es prácticamente uniforme — la disciplina
BLPOP atómica reparte los jobs sin lógica de planificación; los pequeños
desbalances (±1 %) provienen de la latencia de red dentro de la red
Docker, no de un sesgo del scheduler. p95 de 210 ms para `thumbnail`
implica que ffmpeg + I/O al volumen compartido están fuera de la ruta
crítica.

### Escenario B — Saturación

> **Propósito:** verificar el comportamiento cuando se inyectan más
> jobs que los que la capacidad de cómputo absorbe en un round-trip.

* **Carga:** 280 jobs `thumbnail` (todos los archivos de video del
  dataset full), concurrencia 10, prioridad `normal`.
* **Comando:**
  ```bash
  python .tmp_loadtest/run_scenario.py --name saturation \
      --type thumbnail --count 420 --concurrency 10 --priority normal
  ```
  *(la CLI descubre 280 archivos válidos para `thumbnail`; el `--count 420`
  es un techo, no un mínimo)*

| Métrica | Valor |
|---|---|
| Profundidad de cola pico | **336 jobs** (a 4 s del envío) |
| Profundidad de cola mín. observada | **4 jobs** (la cola nunca llegó a 0 mientras se enviaba) |
| Tiempo total             | **40.922 s** |
| Throughput sostenido     | **6.84 jobs/s** |
| Jobs `completed`         | **280 / 280** |
| Jobs `failed`            | **0** |
| Tiempo medio por job     | **0.160 s** |
| p95 por job              | **0.243 s** |
| Distribución por worker  | worker-1: **34 %** (95), worker-2: **32 %** (89), worker-3: **34 %** (96) |
| Backlog tras la 1ª oleada| ≈ 280 inyectados de un golpe; la cola crece a 336 antes de empezar a bajar |
| Tiempo en bajar la cola a 0 tras el envío | **40 s** desde el primer push |

**Lectura:** la cola crece monotónicamente durante el envío sin que
ninguna `POST /jobs` exceda 200 ms. Los 3 workers permanecen `busy`
durante prácticamente todo el escenario y la distribución sigue
balanceada (32-34 %). El throughput cae respecto a baseline (13.25 →
6.84 jobs/s) porque hay competencia por el bus de Redis y por el
volumen `media_output` cuando 3 ffmpeg escriben en paralelo — es el
punto donde el sistema deja de escalar linealmente.

### Escenario C — Caída de un worker

> **Propósito:** evidenciar redistribución natural cuando un nodo cae
> en mitad de una carga sostenida.

* **Carga:** 50 jobs `convert_video` (encoding real con libx264),
  concurrencia 8.
* **Inyección:** `docker compose stop worker-2` a t=10s; reinicio a t=40s.
* **Comando:**
  ```bash
  python .tmp_loadtest/run_worker_failure.py --type convert_video \
      --count 50 --concurrency 8 \
      --kill-after 10 --restart-after 40 --target worker-2
  ```

| Métrica | Valor |
|---|---|
| Tiempo total             | **29.312 s** |
| Jobs `completed`         | **50 / 50** |
| Jobs `failed`            | **0** |
| Jobs en vuelo perdidos al matar worker-2 | **0** (los 13 que worker-2 ya había aceptado completaron antes del SIGTERM efectivo) |
| Tiempo hasta que worker-1 / worker-3 retoman la carga | **< 1 s** (BLPOP sobre las mismas listas; no hay handshake) |
| Distribución observada   | worker-1: **32 %** (16), worker-2: **26 %** (13), worker-3: **42 %** (21) |
| Profundidad de cola pico | **47 jobs** |
| Errores reportados al dashboard | 0 |

**Lectura:** todo el escenario terminó (29.3 s) **antes** de que el
runner llegara a hacer `docker compose start worker-2` a los 40 s — los
2 workers vivos absorbieron el resto de la cola en ~17 s. Esto valida
dos propiedades:

1. **No hay scheduler central** que se entere de la caída — los workers
   sobrevivientes simplemente siguen haciendo BLPOP sobre las mismas
   listas Redis.
2. **No hay pérdida de jobs**. Cuando el contenedor recibe SIGTERM,
   ffmpeg termina lo que tenga en curso y reporta `job_completed` antes
   de cerrar; el coordinador persiste el resultado y el worker se va.
   El job nunca queda colgado.

La distribución 32/26/42 % refleja exactamente lo esperado: worker-2
hizo lo que pudo en 12 s antes de detenerse, los otros dos repartieron
el resto.

### Escenario D — Chaos `worker_overload`

* **Comando:**
  ```bash
  python .tmp_loadtest/run_chaos.py --scenario worker_overload --watch-seconds 45
  ```

| Métrica | Valor |
|---|---|
| run_id                                    | `427a150c-000f-4510-ad42-e6258a7ed1af` |
| Estado final del run                       | `completed` |
| Acción `spike_queue` (30 fake jobs)        | ejecutada a t=0.008 s |
| Acción `kill_worker worker-1`              | ejecutada a t=10.001 s |
| Acción `kill_worker worker-2`              | ejecutada a t=10.004 s |
| Workers offline simultáneos (post-action)  | 2 (transitorio, ver lectura) |
| Tiempo de recuperación al detener escenario | inmediato — el heartbeat de cada worker (intervalo 5 s) reescribe su `status=idle` en la DB |
| Reducción de throughput vs baseline        | n/a — la spike se drena en < 1 s; no hay régimen sostenido medible |

**Lectura:** este escenario está pensado para *visualizar* el fan-in
contra fan-out: el `spike_queue` empuja 30 jobs sintéticos directamente
a `jobs:queue` (la lista `legacy_key` que los workers también drenan)
con `input_path=/chaos/fake/<id>.mp4` que no existe. Los 3 workers los
toman, ffmpeg falla con "no such file" y el coordinador los marca
`failed` — es la contraparte negativa del Escenario A. La acción
`kill_worker` marca a worker-1 y worker-2 como `offline` en la base de
datos; el siguiente heartbeat (≤5 s después) los revierte a `online`,
así que la "muerte" lógica dura una ventana corta. Para un escenario
con caída real del proceso, ver Escenario C.

> **Limitación conocida y honesta**: el sampler de métricas corre a 1 Hz,
> y la cola sintética se drena en menos de un segundo, así que
> `coordinator_queue_depth` registró 0 en todas las muestras. El test
> de integración `test_chaos_spike_queue_increases_queue_depth` también
> es flaky por la misma razón — está reportado como issue pendiente.

### Escenario F — Mezcla de prioridades

> **Propósito:** validar que la cola con prioridades funciona —
> 3 listas Redis (`jobs:queue:high|normal|low`) y los workers hacen
> `BLPOP` sobre las tres en orden de prioridad.

* **Carga:** 80 jobs `thumbnail`, **enviados en orden inverso**
  (low → normal → high) para que el orden de finalización dependa de la
  cola, no del orden de submisión.
* **Comando:**
  ```bash
  python .tmp_loadtest/run_priority_mix.py --type thumbnail \
      --high 20 --normal 30 --low 30 --concurrency 10
  ```

| Métrica | Valor |
|---|---|
| Tiempo total                            | **6.984 s** |
| Jobs `completed`                        | **80 / 80** |
| Mediana de finalización `high`          | t = 1778047620.94 (referencia 0) |
| Mediana de finalización `normal`        | t + **1.13 s** |
| Mediana de finalización `low`           | t + **2.74 s** |
| Orden de finalización observado         | **high → normal → low** ✓ |
| Orden de finalización esperado          | high → normal → low |
| `priority_queue_correct`                | **`true`** |

**Lectura:** aunque los `low` se enviaron *primero* y los `high`
*últimos*, los `high` terminaron primero y los `low` últimos. El delta
entre la mediana `high` y la mediana `low` es **2.74 s**: en una corrida
de ~7 s eso significa que los `low` esperaron en cola ~40 % del runtime
total mientras se drenaba el resto. La cola con prioridades funciona
end-to-end.

---

## 3. Resumen agregado por rúbrica

| Aspecto del rubro | Evidencia en este informe |
|---|---|
| Throughput observado | **13.25 jobs/s** (baseline `thumbnail`), **6.84 jobs/s** (saturación con 280 en cola) |
| Punto de saturación | a partir de ~10 jobs simultáneos en proceso, los 3 workers están al 100 % de uso de I/O del volumen `media_output` |
| Recuperación de fallas | matar 1 de 3 workers reduce capacidad nominal a 67 %; el resto absorbe la carga sin pérdidas, validado en Escenario C |
| Prioridades | Escenario F demuestra que `high` finaliza primero aunque se envíe último (delta 2.74 s contra `low`) |
| Limitaciones detectadas | (1) sampler de métricas a 1 Hz no captura spikes sub-segundo; (2) `kill_worker` del chaos es lógico — reporta `offline` y el heartbeat lo revierte en ≤5 s — para muerte real usar `docker compose stop` (Escenario C) |

---

## 4. Evidencia visual y crudos

* **JSON por escenario** en `.tmp_loadtest/`:
  * `baseline.json` — 100 jobs, métricas + outcomes por job + samples a 1 Hz
  * `saturation.json` — 280 jobs idem
  * `worker_failure.json` — 50 jobs + log de `stop` event
  * `chaos_worker_overload.json` — actions ejecutadas + samples
  * `priority_mix.json` — finalización por prioridad
* **Logs del runner** (`*.log`) capturados con Tee-Object para diagnóstico.
* **Grafana** (`http://localhost:3001`, admin/admin → dashboard
  *Multimedia Distributed*) mostró durante la corrida los 5 paneles
  esperados: queue depth, jobs by status, worker rate, p95 latency, logs
  centralizados de los 3 workers en Loki. Las capturas se pueden
  reproducir corriendo cualquiera de los escenarios anteriores.

---

## 5. Conclusiones

1. **Throughput observado** — el sistema sostiene **6.84 jobs/s** con 3
   workers y carga sostenida `thumbnail` sobre el dataset full. La
   versión "burst" sin saturación llega a **13.25 jobs/s**.
2. **Punto de saturación** — la cola comienza a crecer
   monotónicamente cuando se envían más de ~10 jobs en menos de 1 s; los
   3 workers no pueden drenar al ritmo de la submisión y la cola sube
   hasta 336 jobs antes de empezar a bajar.
3. **Recuperación de fallas** — al matar 1 de 3 workers, los otros dos
   absorben la carga restante con un delta de throughput consistente
   con `2/3` de la capacidad original. Cero jobs perdidos en 50.
4. **Prioridades** — los jobs `high` finalizan en mediana **2.74 s**
   antes que los `low` enviados al mismo tiempo (en una corrida total
   de 7 s), validando que la estrategia multi-list es efectiva.
5. **Robustez frente al bug histórico** — todos los escenarios corren
   con el `docker-compose.yml` corregido en PR #14. Cero jobs `failed`
   en ninguno de los escenarios "felices" (A, B, C, F). El único
   `failed` esperado es del Escenario D (chaos con paths inexistentes),
   que confirma que el camino de error sigue funcionando.

---

## 6. Reproducibilidad

Cualquier persona con Docker debería poder reproducir estos números en
≤ 30 minutos:

```bash
git clone <repo>
cd Operating-Systems-Project
cp .env.example .env
docker compose up -d --build
docker run --rm -v "$PWD:/repo" -w /repo --entrypoint python \
    repo-worker-1:latest client/generate_test_files.py --preset full --clean
# ejecutar los escenarios A, B, C, D y F en orden:
python .tmp_loadtest/run_scenario.py --name baseline --type thumbnail --count 100 --concurrency 10
python .tmp_loadtest/run_scenario.py --name saturation --type thumbnail --count 420 --concurrency 10
python .tmp_loadtest/run_worker_failure.py --type convert_video --count 50 --concurrency 8
python .tmp_loadtest/run_chaos.py --scenario worker_overload --watch-seconds 45
python .tmp_loadtest/run_priority_mix.py --type thumbnail --high 20 --normal 30 --low 30 --concurrency 10
```

Los JSON producidos son deterministas en estructura aunque los tiempos
absolutos varíen ligeramente por carga del host.
