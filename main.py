from fastapi import FastAPI
from routers import umami_router

app = FastAPI()

app.include_router(umami_router.router, prefix="/api/v1/umami")
