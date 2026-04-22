from fastapi import FastAPI

app = FastAPI(title='Dashboard Backend')


@app.get('/status')
def status() -> dict[str, str]:
    return {'dashboard': 'running'}
