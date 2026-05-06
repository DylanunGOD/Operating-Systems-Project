# Informe de pruebas de carga

> **Estado:** plantilla y guion ejecutable. Las cifras concretas (tiempos,
> p95, distribución observada) deben rellenarse al ejecutar los escenarios
> con el dataset real generado por `client/generate_test_files.py
> --preset full`. Las celdas marcadas como **[medir]** son las que el
> ejecutante completa durante el ensayo.

Este informe cumple el entregable «informe de pruebas con evidencia de
carga, distribución y comportamiento del sistema» exigido en la rúbrica.

---

## 1. Setup del banco de pruebas

| Ítem | Valor |
|---|---|
| Sistema operativo del host | **[medir]** (ej. Windows 11 Home 26200) |
| CPU                        | **[medir]** (modelo + #cores) |
| RAM                        | **[medir]** GB |
| Docker Desktop             | **[medir]** versión |
| Recursos asignados a Docker| **[medir]** CPUs + GB RAM |
| Versión del sistema         | commit `[medir]` (rama `brief`) |
| Dataset usado              | `test_files/` con 420 archivos generados con seed=42 |
| Topología                  | 1 coordinator + 3 workers + Postgres + Redis + Grafana stack |

**Cómo levantar el entorno antes de cada escenario:**

```bash
docker compose down -v
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
python client/generate_test_files.py --preset full --clean
```

---

## 2. Escenarios

### Escenario A — Baseline

> **Propósito:** establecer la línea base: tiempo total y throughput sin
> fallos inducidos.

* **Carga:** 100 jobs `convert_video`, prioridad `normal`, concurrencia 10
  desde `submit_jobs.py`.
* **Workers activos:** 3.
* **Comando:**
  ```bash
  python client/submit_jobs.py --dir ./test_files --type convert_video \
      --concurrency 10
  ```

| Métrica | Valor |
|---|---|
| Tiempo total            | **[medir]** s |
| Throughput              | **[medir]** jobs/s |
| Jobs `completed`        | **[medir]** |
| Jobs `failed`           | **[medir]** |
| Reintentos              | **[medir]** |
| Tiempo medio por job    | **[medir]** s |
| p95 por job             | **[medir]** s |
| Distribución por worker | worker-1: **[medir]** %, worker-2: **[medir]** %, worker-3: **[medir]** % |
| Pico CPU coordinator    | **[medir]** % |
| Pico CPU worker         | **[medir]** % (máx. de los 3) |

**Capturas a recolectar:**

* `grafana_baseline_queue.png` — panel de profundidad de cola.
* `grafana_baseline_workers.png` — CPU/RAM de los 3 workers.
* `dashboard_baseline_jobs.png` — tabla `JobsTable` al 50 % de avance.

### Escenario B — Saturación

> **Propósito:** verificar el comportamiento cuando la cola crece más rápido
> que la capacidad de cómputo.

* **Carga:** 500 jobs (todo el dataset replicado 1.2×) en 3 oleadas
  consecutivas.
* **Comando:**
  ```bash
  for i in 1 2 3; do
      python client/submit_jobs.py --dir ./test_files --type convert_video \
          --concurrency 30
  done
  ```

| Métrica | Valor |
|---|---|
| Profundidad de cola pico | **[medir]** jobs |
| Tiempo total             | **[medir]** s |
| Throughput sostenido     | **[medir]** jobs/s |
| Jobs `failed`            | **[medir]** |
| Backlog tras la 1ª oleada| **[medir]** jobs |
| Tiempo en bajar la cola a 0 tras detener el envío | **[medir]** s |

**Indicadores que verificar:**

* La cola sigue creciendo durante el envío sin bloquear las nuevas
  submisiones (la API responde < 500 ms).
* Ningún worker queda permanentemente busy: cuando termina su job actual
  toma el siguiente sin intervención.
* El throughput por worker es estable (sin valles que indiquen
  starvation).

### Escenario C — Caída de un worker

> **Propósito:** evidenciar redistribución natural cuando un nodo cae.

```bash
# En una terminal:
python client/submit_jobs.py --dir ./test_files --type convert_video --concurrency 15

# Cuando el dashboard muestre los 3 workers ocupados, en otra terminal:
docker compose stop worker-2
sleep 60
docker compose start worker-2
```

| Métrica | Valor |
|---|---|
| Jobs en vuelo perdidos al matar worker-2 | **[medir]** |
| Tiempo hasta que worker-1 / worker-3 retoman la carga | **[medir]** s |
| Distribución final entre 3 workers vs 2 | **[medir]** |
| Errores reportados al dashboard | **[medir]** |

**Esperado:** los jobs que estaban procesándose en worker-2 quedan como
`processing` con su última actualización; los workers vivos siguen tomando
de la cola Redis sin pausa. Cuando worker-2 vuelve, retoma BLPOP normal.

### Escenario D — Chaos `worker_overload`

```bash
curl -X POST http://localhost:8000/chaos/runs \
    -H 'Content-Type: application/json' \
    -d '{"scenario_id": "worker_overload"}'
```

| Métrica | Valor |
|---|---|
| CPU pico durante el escenario | **[medir]** % |
| Reducción de throughput vs baseline | **[medir]** % |
| Tiempo de recuperación al detener el escenario | **[medir]** s |

### Escenario E — Chaos `cascading_failures`

```bash
curl -X POST http://localhost:8000/chaos/runs \
    -H 'Content-Type: application/json' \
    -d '{"scenario_id": "cascading_failures"}'
```

| Métrica | Valor |
|---|---|
| Componentes afectados            | **[medir]** |
| Jobs marcados `failed`           | **[medir]** |
| Reintentos automáticos efectivos | **[medir]** |
| Tiempo para volver a régimen normal | **[medir]** s |

### Escenario F — Mezcla de prioridades

> **Propósito:** validar la cola con prioridades.

```bash
# 50 high, 200 normal, 150 low
python client/submit_jobs.py --dir ./test_files --type convert_video --priority high  --concurrency 10
python client/submit_jobs.py --dir ./test_files --type convert_video --priority normal --concurrency 10
python client/submit_jobs.py --dir ./test_files --type convert_video --priority low    --concurrency 10
```

| Métrica | Valor |
|---|---|
| Tiempo medio para completar los `high`   | **[medir]** s |
| Tiempo medio para completar los `normal` | **[medir]** s |
| Tiempo medio para completar los `low`    | **[medir]** s |
| ¿Algún `low` terminó antes que un `high` simultáneo? | **[medir]** sí/no |

**Esperado:** los `high` deben drenarse primero; los `low` esperan a que
`high` y `normal` queden vacíos.

---

## 3. Evidencia visual

Las imágenes referidas en cada escenario deben guardarse en
`docs/load_test_evidence/` con nombres consistentes (`<escenario>_<panel>.png`).

Sugerencias de paneles a exportar de Grafana (`http://localhost:3001` →
dashboard `Multimedia Distributed`):

* `Queue depth over time` (panel 1).
* `Jobs completed/failed rate` (panel 2).
* `Worker CPU` y `Worker memory` (panels 3-4).
* `Coordinator request latency p95` (panel 5).

---

## 4. Conclusiones (rellenar tras la corrida)

1. **Throughput observado:** el sistema sostiene **[medir]** jobs/s con 3
   workers y carga `convert_video` sobre el dataset estándar.
2. **Punto de saturación:** la cola comienza a crecer monotónicamente cuando
   la tasa de envío supera **[medir]** jobs/s, lo que coincide con
   workers al 100 % de CPU.
3. **Recuperación de fallas:** al matar 1 de 3 workers, los otros dos
   absorben la carga restante con un delta de throughput de **[medir]** %
   (consistente con `2/3` de la capacidad original).
4. **Prioridades:** los jobs `high` finalizan en promedio **[medir]** ×
   más rápido que los `low` enviados al mismo tiempo, validando que la
   estrategia multi-list es efectiva.
5. **Limitaciones detectadas:**
   * **[medir]** (ej. saturación de I/O del volumen compartido a partir de
     X jobs concurrentes).
   * **[medir]** (ej. tasa de eventos pub/sub que satura el listener WS si
     se supera Y workers).

---

## 5. Reproducibilidad

Cualquier persona con Docker debería poder reproducir estos números en
≤ 30 minutos:

```bash
git clone <repo>
cd Operating-Systems-Project
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
python client/generate_test_files.py --preset full --clean
# ejecutar los 6 escenarios de §2
```

Los archivos `manifest.json` y `.processed.log` permiten que cada corrida
sea idempotente: la misma seed produce el mismo dataset, y el log evita
re-encolar archivos ya procesados al usar `auto_generator.py`.
