from fastapi import FastAPI

app = FastAPI(title="Coordinator API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
