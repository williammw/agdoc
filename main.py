from fastapi import FastAPI
from routers import umami_router
from routers import agi_router


app = FastAPI()

app.include_router(umami_router.router, prefix="/api/v1/umami")
app.include_router(agi_router.router, prefix="/api/v1/agi")


@app.get("/")
async def greeting():
    return {"message": "Hello from Agi API!"}
