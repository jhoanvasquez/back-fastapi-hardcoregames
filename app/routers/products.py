from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse, JSONResponse
import json
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from ..database import get_session
from ..repositories.products import ProductRepository
from ..models import Product, GameDetail, Consoles, Licenses

router = APIRouter(prefix="/products", tags=["products"])


@router.get("/")
async def list_products(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Product).options(selectinload(Product.consoles)).order_by(Product.id_product)
    )
    products = result.scalars().all()

    data = [
        {
            "id_product": p.id_product,
            "title": p.title,
            "description": p.description,
            "date_register": p.date_register.isoformat() if getattr(p, "date_register", None) else None,
            "date_last_modified": p.date_last_modified.isoformat() if getattr(p, "date_last_modified", None) else None,
            "image": p.image,
            "calification": p.calification,
            "puntos_venta": p.puntos_venta,
            "puede_rentarse": p.puede_rentarse,
            "destacado": p.destacado,
            "consoles": [
                {"id_console": c.id_console}
                for c in getattr(p, "consoles", []) or []
            ],
        }
        for p in products
    ]
    return {"data": data}

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

    data = [
        {
            "id_product": p.id_product,
            "title": p.title,
            "description": p.description,
            "date_register": p.date_register.isoformat() if getattr(p, "date_register", None) else None,
            "date_last_modified": p.date_last_modified.isoformat() if getattr(p, "date_last_modified", None) else None,
            "image": p.image,
            "calification": p.calification,
            "puntos_venta": p.puntos_venta,
            "puede_rentarse": p.puede_rentarse,
            "destacado": p.destacado,
            "type_id_id": p.type_id_id,
            "tipo_juego_id": p.tipo_juego_id,
            "consoles": [
                {"id_console": c.id_console}
                for c in getattr(p, "consoles", []) or []
            ],
        }
        for p in products
    ]
    return {"data": data}


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
            "destacado": p.destacado

        }
        for p in products
    ]

    return {"data": data}


@router.get("/search")
async def search_products(q: str, limit: int = 20, use_trgm: bool = False, session: AsyncSession = Depends(get_session)):
    if not q:
        return {"data": []}

    pattern = f"%{q}%"
    base = select(Product).where(
        or_(Product.title.ilike(pattern), Product.title.ilike(pattern))
    ).limit(limit)

    if use_trgm:
        base = base.order_by(func.similarity(Product.title, q).desc())

    result = await session.execute(base)
    products = result.scalars().all()

    data = [
        {
            "id_product": p.id_product,
            "title": p.title,
            "description": p.description,
            "date_register": p.date_register.isoformat() if getattr(p, "date_register", None) else None,
            "image": p.image,
            "calification": p.calification,
            "puntos_venta": p.puntos_venta,
        }
        for p in products
    ]
    return {"data": data}


@router.get("/{id_product}")
async def get_product_by_id(id_product: int, session: AsyncSession = Depends(get_session)):

    result = await session.execute(select(Product).filter(Product.id_product == id_product))
    product = result.scalars().first()

    if not product:
        payload = {'message': 'producto no existente', 'data': [], 'code': '00', 'status': 200}
        return JSONResponse(payload)

    # primer precio (para resumen)
    res_price = await session.execute(
        select(GameDetail).filter(GameDetail.producto_id == id_product, GameDetail.precio > 0).limit(1)
    )
    prices_game = res_price.scalars().first()

    # stock total disponible (stock > 0)
    res_stock = await session.execute(
        select(func.sum(GameDetail.stock)).filter(GameDetail.producto_id == id_product, GameDetail.stock > 0)
    )
    stock_sum = res_stock.scalar() or 0

    # Obtener detalles agrupados por (consola, licencia, duracion), ordenados por precio ascendente
    details_query = (
        select(
            GameDetail.id_game_detail,
            GameDetail.producto_id,
            GameDetail.consola_id,
            GameDetail.licencia_id,
            GameDetail.cuenta_id,
            GameDetail.duracion_dias_alquiler,
            GameDetail.stock,
            GameDetail.precio,
            GameDetail.precio_descuento,
            Consoles.descripcion.label("desc_console"),
            Licenses.descripcion.label("desc_licence"),
        )
        .select_from(GameDetail)
        .join(Consoles, GameDetail.consola_id == Consoles.id_console, isouter=True)
        .join(Licenses, GameDetail.licencia_id == Licenses.id_license, isouter=True)
        .distinct(GameDetail.consola_id, GameDetail.licencia_id, GameDetail.duracion_dias_alquiler)
        .where(GameDetail.producto_id == id_product)
        .order_by(
            GameDetail.consola_id,
            GameDetail.licencia_id,
            GameDetail.duracion_dias_alquiler,
            GameDetail.precio.asc(),
        )
    )

    res_details = await session.execute(details_query)
    rows = res_details.all()

    details = [
        {
            "pk": row.id_game_detail,
            "consola": row.consola_id,
            "desc_console": row.desc_console or "",
            "licencia": row.licencia_id,
            "desc_licence": row.desc_licence or "",
            "stock": row.stock,
            "precio": row.precio,
            "precio_descuento": row.precio_descuento,
            "duracion_dias_alquiler": row.duracion_dias_alquiler,
        }
        for row in rows
    ]
    details.sort(key=lambda x: ((x.get("precio") or 0) == 0, x.get("precio") or 0))

    data = {
        "id_product": product.id_product,
        "title": getattr(product, "title", None),
        "description": getattr(product, "description", None),
        "date_register": product.date_register.isoformat() if getattr(product, "date_register", None) else None,
        "date_last_modified": getattr(product, "date_last_modified").isoformat() if getattr(product, "date_last_modified", None) else None,
        "image": getattr(product, "image", None),
        "calification": getattr(product, "calification", None),
        "puntos_venta": getattr(product, "puntos_venta", None),
        "puede_rentarse": getattr(product, "puede_rentarse", None),
        "destacado": getattr(product, "destacado", None),
        "stock": stock_sum,
        "precio_descuento": getattr(prices_game, "precio_descuento", None) if prices_game else None,
        "price": getattr(prices_game, "precio", None) if prices_game else None,
        "details": details,
    }

    payload = {'message': 'proceso exitoso', 'data': data, 'code': '00', 'status': 200}
    return JSONResponse(payload)