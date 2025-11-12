from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse
import json
from sqlalchemy import select
from ..database import get_session
from ..repositories.products import ProductRepository
from ..models import Product

router = APIRouter(prefix="/products", tags=["products"])

@router.get("/")
async def list_products(session: AsyncSession = Depends(get_session)):
    return await ProductRepository.get_all(session)

@router.get("/stream")
async def stream_numbers():
    async def event_generator():
        counter = 0
        while True:
            counter += 1
            yield f"data: message {counter}\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/pagination")
async def get_products(after_id: int | None = None, limit: int = 10, session: AsyncSession = Depends(get_session)):
    query = select(Product).order_by(Product.id_product)
    if after_id:
        query = query.filter(Product.id_product > after_id)
    query = query.limit(limit)
    result = await session.execute(query)
    products = result.scalars().all()
    next_cursor = products[-1].id_product if products else None
    return {"data": products, "next_cursor": next_cursor}


@router.get("/favorites")
async def get_favorites(limit: int = 20, session: AsyncSession = Depends(get_session)):
    """
    Obtener productos marcados como favoritos (destacado=True) ordenados por calification (desc).
    """
    query = select(Product).where(Product.destacado.is_(True)).order_by(Product.calification.desc()).limit(limit)
    result = await session.execute(query)
    products = result.scalars().all()

    # serializar a dicts simples para respuesta JSON
    data = [
        {
            "id_product": p.id_product,
            "title": p.title,
            "description": p.description,
            "date_register": p.date_register.isoformat() if p.date_register else None,
            "date_last_modified": p.date_last_modified.isoformat() if getattr(p, "date_last_modified", None) else None,
            "image": p.image,
            "calification": p.calification,
            "puntos_venta": p.puntos_venta,
            "puede_rentarse": p.puede_rentarse,
            "destacado": p.destacado,
        }
        for p in products
    ]

    return {"data": data}

@router.get("/favorites")
async def get_favorites(limit: int = 20, session: AsyncSession = Depends(get_session)):
    query = select(Product).where(Product.destacado.is_(True)).order_by(Product.calification.desc()).limit(limit)
    result = await session.execute(query)
    products = result.scalars().all()
    data = [
        {
            "id_product": p.id_product,
            "title": p.title,
            "description": p.description,
            "date_register": p.date_register.isoformat() if p.date_register else None,
            "date_last_modified": p.date_last_modified.isoformat() if getattr(p, "date_last_modified", None) else None,
            "image": p.image,
            "calification": p.calification,
            "puntos_venta": p.puntos_venta,
            "puede_rentarse": p.puede_rentarse,
            "destacado": p.destacado,
        }
        for p in products
    ]