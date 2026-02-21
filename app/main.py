from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth
from .routers import products
from .routers import liked_games
from .routers import order_buy
from .routers import coupons
from .routers import shopping_car
from .database import Base, engine

app = FastAPI(title="Reactive FastAPI Microservice")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

app.include_router(products.router)
app.include_router(auth.router)
app.include_router(liked_games.router)
app.include_router(order_buy.router)
app.include_router(shopping_car.router)
app.include_router(coupons.router)