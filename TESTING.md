# Guía de pruebas end-to-end

Cómo validar el dashboard + backend + chaos + Grafana después de los cambios del frontend.

## 1. Levantar el stack (backend + infra)

```bash
cd "D:/U progra/VI Semestre/Sistemas Operativos/Proyecto 1/Operating-Systems-Project"
cp .env.example .env   # si no existe
docker compose up -d --build
```

Esperá ~30-60s y verificá que está vivo:

```bash
curl http://localhost:8000/health           # {"status":"healthy",...}
curl http://localhost:8000/chaos/scenarios  # debe listar 4 escenarios
```

## 2. Levantar el dashboard en dev

```bash
cd dashboard
npm install   # si no lo hiciste antes
npm run dev
```

Abrí http://localhost:3000. Chequeos rápidos:

- **Header** debe decir "En línea". Si sale "Reconectando…" el WS no conecta → revisá que coordinator esté en :8000.
- **DevTools → Network → WS** debe tener una conexión abierta a `ws://localhost:8000/ws`, y cada 5s llega un frame `{"type":"queue_snapshot",...}`.

## 3. Generar tráfico para ver jobs en vivo

En otra terminal:

```bash
cd "D:/U progra/VI Semestre/Sistemas Operativos/Proyecto 1/Operating-Systems-Project"
python client/generate_test_files.py --count 10 --duration 3
python client/submit_jobs.py --dir ./test_files --type convert_video --concurrency 3
```

Qué tiene que pasar en el dashboard (sin F5):

- La tabla **Jobs** se puebla en ~15s (primer refresh REST).
- Apenas un worker toma el job: aparece `processing`, `worker_id` poblado, barra de progreso subiendo 0→100.
- Al terminar: badge verde `completed`.
- Las **métricas superiores** (Cola / Procesando / Completados) se mueven en vivo.

## 4. Probar WorkersStatus

Con jobs corriendo, las cards de worker deben mostrar:

- Estado `busy` ↔ `idle` alternando.
- CPU/RAM actualizándose cada 3s.
- Jobs completados incrementando.

## 5. Probar el Chaos Panel

En el dashboard:

1. Seleccioná **"Worker Overload · 30s"** → **Ejecutar**. Aparece el bloque azul con el run activo, contador subiendo (0s → 30s), y lista de acciones ejecutadas (`spike_queue`, `kill_worker`, ...).
2. Mientras corre, probá **Ejecutar** de nuevo sin cancelar → debe salir banner amarillo "Ya hay un escenario en ejecución" (esto testea el 409).
3. Clickeá **Cancelar** → el run pasa a `cancelled` y aparece en el historial.
4. Probá los otros:
   - `redis_outage` — la cola se vacía abruptamente.
   - `cascading_failures` — vas a ver jobs fallando (badge rojo) en la tabla.
   - `slow_network` — los jobs tardan ~2s más.

Verificá vía API que los escenarios arrancan:

```bash
curl http://localhost:8000/chaos/runs   # lista runs activos e históricos
```

## 6. Probar reconexión del WS

```bash
docker compose restart coordinator
```

El header debe pasar a "Reconectando…", y volver a "En línea" solo en ~2-5s. Los jobs en la tabla quedan (el store no se limpia).

## 7. Verificar Grafana

http://localhost:3001 (admin/admin) → dashboard **"Multimedia Platform"**. Con jobs + chaos corriendo vas a ver:

- **Queue Depth** subiendo con `spike_queue`.
- **Failure Rate (5m)** pasando de verde a rojo durante `cascading_failures`.
- **Avg Job Duration** saltando durante `slow_network`.
- **Worker Heartbeat Age** en verde (<10s) mientras los workers están vivos.

## 8. Backend tests (opcional — ya están verdes en CI)

```bash
pytest tests/ -v                           # 84 unitarios
RUN_INTEGRATION_TESTS=1 pytest tests/ -v   # +6 integración (necesita docker)
```

## Debugging

Si algo falla, los lugares más útiles:

- `docker compose logs -f coordinator` — WS + chaos logs.
- `docker compose logs -f worker-1` — ffmpeg + progreso.
- **DevTools → Console** del navegador — errores del store/ChaosPanel.
- http://localhost:8000/docs — Swagger para probar endpoints a mano.
