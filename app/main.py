from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routes import statement_routes

app = FastAPI(
    title="Bank Statement API",
    version="1.0.0"
)

# ----------------------------
# CORS Configuration
# ----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],          # GET, POST, PUT, DELETE, OPTIONS
    allow_headers=["*"],          # Allow all headers
    expose_headers=["*"],
)

# ----------------------------
# Static Files
# ----------------------------
app.mount(
    "/uploads",
    StaticFiles(directory="app/uploads"),
    name="uploads"
)

# ----------------------------
# Routes
# ----------------------------
app.include_router(
    statement_routes.router,
    prefix="/api/v1/statement",
    tags=["Bank Statement"]
)

# ----------------------------
# Health Check
# ----------------------------
@app.get("/")
async def health_check():
    return {
        "status": "running"
    }