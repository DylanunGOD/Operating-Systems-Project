# Client — CLI Tools

Two standalone scripts for the distributed multimedia processing platform.

## Requirements

- Python 3.11+
- `httpx>=0.25` — install with `pip install -r client/requirements.txt`
- `ffmpeg` on PATH — only required for `generate_test_files.py`

---

## `submit_jobs.py` — Batch job submission

Scans a directory for media files and submits one job per file to the coordinator API.

### Options

| Flag | Default | Description |
|---|---|---|
| `--dir PATH` | *(required)* | Directory of input files |
| `--type TYPE` | *(required)* | `convert_video`, `extract_audio`, or `thumbnail` |
| `--coordinator URL` | `http://localhost:8000` | Coordinator base URL |
| `--params-json JSON` | `{}` | Extra params forwarded to each job |
| `--concurrency N` | `10` | Max concurrent HTTP submissions |
| `--output-dir PATH` | `/media/output` | Output directory written into job params |
| `--no-progress` | off | Disable live progress line |

### Examples

```bash
# Submit all videos in /media/input as convert_video jobs
python client/submit_jobs.py --dir /media/input --type convert_video

# Submit 5 files at a time, write output to /tmp/out
python client/submit_jobs.py \
    --dir /media/input \
    --type thumbnail \
    --concurrency 5 \
    --output-dir /tmp/out

# Against a remote coordinator, quiet mode
python client/submit_jobs.py \
    --dir ./test_files \
    --type extract_audio \
    --coordinator http://coordinator:8000 \
    --no-progress
```

### Expected output

```
Found 10 file(s) in './test_files'. Submitting to http://localhost:8000 ...
[10/10] submitted | 0 failed

--- Summary ---
Total files  : 10
Succeeded    : 10
Failed       : 0
Elapsed      : 1.23s
```

Exit code `0` if all jobs were accepted, `1` if any failed.

---

## `generate_test_files.py` — Synthetic test video generator

Creates MP4 test files using `ffmpeg` with a colour-bar video and 1 kHz sine tone.

### Options

| Flag | Default | Description |
|---|---|---|
| `--count N` | `10` | Number of files to generate |
| `--duration SECONDS` | `5` | Duration of each video |
| `--output-dir PATH` | `./test_files` | Destination directory (created if missing) |
| `--resolution WxH` | `320x240` | Video resolution |

### Examples

```bash
# Generate 10 five-second videos (default settings)
python client/generate_test_files.py

# Generate 3 videos, 2 s each, higher resolution
python client/generate_test_files.py --count 3 --duration 2 --resolution 640x480

# Custom output directory
python client/generate_test_files.py --count 20 --output-dir /media/input
```

### Expected output

```
[1/10] generated test_001.mp4 (5s, 320x240)
[2/10] generated test_002.mp4 (5s, 320x240)
...
[10/10] generated test_010.mp4 (5s, 320x240)
```

Already-existing files are skipped (idempotent).

---

## End-to-end demo script

```bash
# 1. Generate test media
python client/generate_test_files.py --count 10 --output-dir /media/input

# 2. Submit jobs
python client/submit_jobs.py \
    --dir /media/input \
    --type convert_video \
    --coordinator http://localhost:8000

# 3. Check results
curl http://localhost:8000/jobs | python -m json.tool
```
