"""BIO - Biomass/Biogas Power Plant Physics Simulation Engine

FastAPI backend for real-time biomass/biogas power plant simulation.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.api.routes import simulation, websocket, scenarios, controls, health
from backend.api.routes import fermentation, fermentation_ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    # Startup
    print(f"Starting {settings.PROJECT_NAME} v{settings.VERSION}")
    yield
    # Shutdown
    print("Shutting down BIO Engine...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Biomass/Biogas Power Plant Physics Simulation Engine",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(health.router, tags=["health"])
app.include_router(
    simulation.router,
    prefix=f"{settings.API_V1_STR}/simulation",
    tags=["simulation"],
)
app.include_router(
    websocket.router,
    prefix=f"{settings.API_V1_STR}/ws",
    tags=["websocket"],
)
app.include_router(
    scenarios.router,
    prefix=f"{settings.API_V1_STR}/scenarios",
    tags=["scenarios"],
)
app.include_router(
    controls.router,
    prefix=f"{settings.API_V1_STR}/controls",
    tags=["controls"],
)
app.include_router(
    fermentation.router,
    prefix=f"{settings.API_V1_STR}/fermentation",
    tags=["fermentation"],
)
app.include_router(
    fermentation_ws.router,
    prefix=f"{settings.API_V1_STR}/fermentation-ws",
    tags=["fermentation-ws"],
)
