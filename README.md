# multimedia-distributed

Plataforma distribuida de procesamiento multimedia que distribuye la carga de trabajo entre multiples nodos coordinados, permitiendo procesar cientos de archivos de video y audio en paralelo con monitoreo en tiempo real y resiliencia ante fallos.

Proyecto academico desarrollado en el contexto de Sistemas Operativos. Demuestra conceptos de procesos concurrentes, colas de tareas, planificacion, comunicacion entre procesos y sistemas distribuidos.

---

## Descripcion

El sistema procesa archivos multimedia mediante tres operaciones principales: conversion de formato, extraccion de audio y generacion de miniaturas. En lugar de ejecutar estas operaciones de forma secuencial en una sola maquina, distribuye el trabajo entre multiples workers que consumen una cola compartida, reduciendo el tiempo total de procesamiento de forma proporcional al numero de nodos activos.

Una instancia con tres workers procesa 600 archivos aproximadamente tres veces mas rapido que una sola maquina.

---

## Arquitectura

El sistema se divide en tres capas:

**Entrada.** El cliente envia trabajos a la API REST del coordinador. Cada trabajo especifica el tipo de operacion, la ruta del archivo de entrada y parametros opcionales como formato de salida o calidad.

**Orquestacion.** El coordinador (FastAPI) recibe los trabajos, los persiste en PostgreSQL y los encola en Redis. Expone un endpoint WebSocket que transmite actualizaciones de progreso a los clientes conectados.

**Ejecucion.** Los workers consumen la cola mediante `BLPOP` (operacion bloqueante de Redis), ejecutan `ffmpeg` en background, y publican el progreso cada segundo. Si un worker falla durante el procesamiento, el trabajo vuelve automaticamente a la cola para ser retomado por otro nodo.

```
Cliente  ->  Coordinador (FastAPI)  ->  Redis (cola)  ->  Worker 1
                                    ->  PostgreSQL         Worker 2
                                    ->  WebSocket /ws      Worker 3
```

---

## Tecnologias

| Componente        | Tecnologia         | Version |
|-------------------|--------------------|---------|
| API del coordinador | FastAPI + Uvicorn | 0.111+  |
| ORM               | SQLAlchemy async   | 2.0     |
| Cola distribuida  | Redis              | 7.x     |
| Persistencia      | PostgreSQL         | 15      |
| Procesamiento     | ffmpeg             | 6.x     |
| Contenedores      | Docker + Compose   | 24+     |
| Logs              | Loki + Promtail    | 2.9     |
| Metricas          | Prometheus         | 2.x     |
| Visualizacion     | Grafana            | 10.x    |
| Dashboard         | React + Vite       | 18 / 5  |

---

## Requisitos

- Docker Desktop 24 o superior
- Docker Compose v2
- Python 3.11+ (solo para el cliente CLI y los tests)
- 4 GB de RAM disponibles para el stack completo
- ffmpeg instalado localmente (opcional, solo para generar archivos de prueba)

---

## Instalacion

### 1. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/multimedia-distributed.git
cd multimedia-distributed
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
```

El archivo `.env` funciona sin modificaciones para entornos locales. Ajustar `POSTGRES_PASSWORD` y credenciales de Grafana si se despliega en un servidor compartido.

### 3. Levantar el stack completo

```bash
docker-compose up --build
```

Esto inicia los siguientes servicios: PostgreSQL, Redis, el coordinador, tres workers, el dashboard, Prometheus, Grafana y Loki.

La primera vez puede tardar varios minutos mientras se descargan las imagenes base y se instalan dependencias.

### 4. Verificar que todo funciona

```bash
# Estado de los contenedores
docker-compose ps

# API del coordinador
curl http://localhost:8000/health

# Dashboard
# Abrir http://localhost:3000 en el navegador

# Grafana
# Abrir http://localhost:3000 (usuario: admin, contrasena: admin)
```

---

## Uso

### Enviar un trabajo individual

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "type": "convert_video",
    "input_path": "/media/input/video.mov",
    "params": {"format": "mp4", "quality": "high"}
  }'
```

Tipos de trabajo disponibles: `convert_video`, `extract_audio`, `thumbnail`.

### Enviar trabajos en lote

```bash
# Generar archivos de prueba (requiere ffmpeg local)
python client/generate_test_files.py --count 50 --duration 10

# Enviar todos los archivos de un directorio
python client/submit_jobs.py --dir ./test_files --type convert_video
```

### Consultar el estado de un trabajo

```bash
curl http://localhost:8000/jobs/{id}
```

### Ver todos los trabajos activos

```bash
curl http://localhost:8000/jobs?status=processing
```

---

## API Reference

| Metodo | Ruta                  | Descripcion                             |
|--------|-----------------------|-----------------------------------------|
| POST   | `/jobs`               | Crear un nuevo trabajo                  |
| GET    | `/jobs`               | Listar trabajos (filtros: status, worker_id) |
| GET    | `/jobs/{id}`          | Detalle de un trabajo                   |
| DELETE | `/jobs/{id}`          | Cancelar un trabajo pendiente           |
| GET    | `/workers`            | Estado actual de todos los workers      |
| GET    | `/metrics`            | Throughput, longitud de cola y recursos |
| POST   | `/chaos/{scenario}`   | Ejecutar un escenario de chaos          |
| WS     | `/ws`                 | Stream de eventos en tiempo real        |

La documentacion interactiva (Swagger UI) esta disponible en `http://localhost:8000/docs`.

---

## Escalar workers

Agregar un cuarto worker no requiere cambios en el codigo. En `docker-compose.yml`, duplicar la definicion de cualquier worker con un nombre distinto:

```yaml
worker-4:
  build: ./worker
  hostname: worker-4
  env_file: .env
  volumes:
    - media_volume:/media
  depends_on:
    - redis
    - postgres
```

El coordinador detecta el nuevo nodo automaticamente en el siguiente heartbeat.

---

## Chaos Engineering

El modulo de chaos engineering permite verificar que el sistema se recupera ante fallos reales. Los escenarios disponibles son:

- `redis_crash` - Detiene Redis por 10 segundos y verifica que los workers se reconectan
- `worker_kill` - Mata worker-2 abruptamente durante un trabajo activo
- `network_latency` - Agrega 500ms de latencia entre el coordinador y PostgreSQL
- `disk_full` - Llena el volumen de salida para verificar el manejo de errores de disco
- `cascading_failure` - Secuencia de fallos: worker-1 cae, latencia en Redis, worker-2 cae
- `total_outage` - Detiene coordinador y Redis simultaneamente

Ejecutar un escenario:

```bash
curl -X POST http://localhost:8000/chaos/worker_kill
```

Cada evento de chaos queda registrado en PostgreSQL y aparece marcado en los graficos de Grafana.

---

## Observabilidad

**Dashboard (React):** `http://localhost:3000`
Muestra el estado de cada trabajo, los recursos de cada worker (CPU y RAM), el historial de eventos y un stream de logs en vivo. Se actualiza cada segundo via WebSocket sin recargar la pagina.

**Grafana:** `http://localhost:4000`
Contiene un dashboard preconfigurado con graficos de throughput, longitud de la cola, tasa de fallos y uso de recursos por nodo. Los eventos de chaos aparecen como lineas verticales.

**Loki:** accesible desde el panel Explore de Grafana.
Permite buscar logs por `job_id`, `worker_id` o nivel de severidad. Ejemplo de query:

```
{job="worker-1"} | json | job_id="550e8400-e29b-41d4-a716-446655440000"
```

**Prometheus:** `http://localhost:9090`
Metricas exportadas: `jobs_total`, `jobs_failed_total`, `processing_duration_seconds`, `queue_length`.

---

## Tests

```bash
# Instalar dependencias de desarrollo
pip install -r requirements-dev.txt

# Correr todos los tests
pytest tests/ -v

# Con reporte de cobertura
pytest tests/ --cov=coordinator --cov=worker --cov-report=term-missing

# Solo tests de integracion (requiere Docker)
pytest tests/test_integration.py -v
```

Los tests de integracion levantan un stack de prueba con `docker-compose -f docker-compose.test.yml`, envian trabajos reales y verifican los resultados en PostgreSQL.

---

## Estructura del proyecto

```
multimedia-distributed/
├── coordinator/          API FastAPI (coordinador)
├── worker/               Servicio worker (replicable)
├── dashboard/            Frontend React
├── chaos/                Modulo de chaos engineering
├── client/               CLI para enviar trabajos
├── infra/
│   ├── postgres/         Schema SQL inicial
│   ├── redis/            Configuracion de Redis
│   ├── grafana/          Dashboards y datasources
│   └── prometheus/       Configuracion de scraping
├── tests/                Suite de tests
├── docker-compose.yml    Orquestacion principal
├── .env.example          Plantilla de variables de entorno
└── MASTER_PLAN.md        Plan de desarrollo por fases
```

---

## Conceptos de Sistemas Operativos demostrados

- **Procesos concurrentes:** multiples workers ejecutan ffmpeg en paralelo mediante `asyncio` y `subprocess`
- **Colas de tareas:** Redis como estructura de scheduling distribuido con operaciones atomicas
- **Planificacion:** asignacion dinamica de trabajos al primer worker disponible via `BLPOP`
- **Comunicacion entre procesos:** REST API, WebSocket y pub/sub de Redis entre componentes
- **Monitoreo de recursos:** CPU, memoria y throughput por nodo via `psutil` y Prometheus
- **Sistemas distribuidos:** coordinacion, resiliencia y consistencia eventual entre nodos independientes

---

## Licencia

MIT
