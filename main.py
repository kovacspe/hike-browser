

from fastapi import FastAPI
from database.models import init_models
from routers.frontend import frontend_router
from routers.trips import trips_router


app = FastAPI(title="Itinerary Manager")
app.include_router(trips_router)
app.include_router(frontend_router)


@app.on_event("startup")
async def on_startup():
    await init_models()
