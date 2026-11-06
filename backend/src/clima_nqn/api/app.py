from fastapi import FastAPI

app = FastAPI(title="clima-nqn")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
