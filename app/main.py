from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import statement_routes

app = FastAPI(
    title="Bank Statement API",
    version="1.0.0"
)

# Serve uploaded files
app.mount(
    "/uploads",
    StaticFiles(directory="app/uploads"),
    name="uploads"
)

app.include_router(
    statement_routes.router,
    prefix="/api/v1/statement",
    tags=["Bank Statement"]
)

@app.get("/")
def health_check():
    return {
        "status": "running"
    }