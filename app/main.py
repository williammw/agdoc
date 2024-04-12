
from fastapi import FastAPI
# Your database and router imports remain the same
from app.routers import umami_router, agi_router, dev_router, cdn_router, tvibkr_router, agents_router
from .lifespan import app_lifespan

app = FastAPI(lifespan=app_lifespan)





app.include_router(umami_router.router, prefix="/api/v1/umami")
app.include_router(agi_router.router, prefix="/api/v1/agi")
app.include_router(cdn_router.router, prefix="/api/v1/cdn")
app.include_router(dev_router.router, prefix="/api/v1/dev")
app.include_router(tvibkr_router.router, prefix="/api/v1/tvibkr")
app.include_router(agents_router.router, prefix="/api/v1/agents")


@app.get("/")
async def greeting():
    return {"message": "Hello from  MEE API!"}






