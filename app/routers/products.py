from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse, JSONResponse
import json
import asyncio
from sqlalchemy import select, func, or_, cast, Integer
from sqlalchemy.orm import selectinload
from ..database import get_session
from ..repositories.products import ProductRepository
from ..models import Product, GameDetail, Consoles, Licenses, Coupon, User
from ..util.util_auth import get_current_user

router = APIRouter(prefix="/products", tags=["products"])


@router.get("/")
async def list_products(
    search: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    query = select(Product).options(selectinload(Product.consoles)).order_by(Product.id_product)

    if search:
        pattern = f"%{search}%"
        query = query.where(Product.title.ilike(pattern))

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
            "type_id": p.type_id_id,
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


@router.get("/by-type/{type_id}")
async def get_products_by_type(
    type_id: int,
    session: AsyncSession = Depends(get_session),
):
    """List products filtered by ``type_id_id``.

    Returns the same basic structure as the main /products list
    endpoint, but only for products where Product.type_id_id
    matches the given ``type_id``.
    """

    # Database column is numeric; cast model field to Integer for safe comparison
    query = (
        select(Product)
        .options(selectinload(Product.consoles))
        .where(cast(Product.type_id_id, Integer) == type_id)
        .order_by(Product.id_product)
    )

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
            "consoles": [
                {"id_console": c.id_console}
                for c in getattr(p, "consoles", []) or []
            ],
        }
        for p in products
    ]
    return {"data": data}


@router.get("/by-console/{console_id}")
async def get_products_by_console(
    console_id: int,
    session: AsyncSession = Depends(get_session),
):
    """List products filtered by console (platform).

    Returns the same basic structure as the main /products list
    endpoint, but only for products associated with the given
    ``console_id``.
    """

    query = (
        select(Product)
        .join(Product.consoles)
        .options(selectinload(Product.consoles))
        .where(Consoles.id_console == console_id)
        .order_by(Product.id_product)
    )

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
            "type_id": p.type_id_id,
            "consoles": [
                {"id_console": c.id_console}
                for c in getattr(p, "consoles", []) or []
            ],
        }
        for p in products
    ]
    return {"data": data}


@router.get("/by-game-type/{game_type_id}")
async def get_products_by_game_type(
    game_type_id: int,
    session: AsyncSession = Depends(get_session),
):
    """List products filtered by ``tipo_juego_id`` (game type).

    Returns the same basic structure as the main /products list
    endpoint, but only for products where Product.tipo_juego_id
    matches the given ``game_type_id``.
    """

    query = (
        select(Product)
        .options(selectinload(Product.consoles))
        .where(cast(Product.tipo_juego_id, Integer) == game_type_id)
        .order_by(Product.id_product)
    )

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
            "type_id": p.type_id_id,
            "consoles": [
                {"id_console": c.id_console}
                for c in getattr(p, "consoles", []) or []
            ],
        }
        for p in products
    ]
    return {"data": data}


@router.get("/combination-price/{id_product}")
async def get_combination_price_by_game(id_product: int, session: AsyncSession = Depends(get_session)):
    """Get optimized price combinations for a product.

    The response groups game details by the combination of
    (``consola``, ``licencia``, ``duracion_dias_alquiler``, ``precio``,
    ``precio_descuento``) and aggregates their stock.

    Each item in ``data`` has the shape:

    {
        "pk": int,  # representative id_game_detail for the group
        "consola": int,
        "desc_console": str,
        "licencia": int,
        "desc_licence": str,
        "stock": int,  # total stock for that combination
        "precio": int,
        "precio_descuento": int,
        "duracion_dias_alquiler": int,
    }
    """

    # Obtener el tipo de producto (equivalente a product.type_id.id_product_type en Django)
    result_product = await session.execute(
        select(Product).filter(Product.id_product == id_product)
    )
    product = result_product.scalars().first()
    product_type = getattr(product, "type_id_id", None) if product else None

    # Traer cada GameDetail que cumpla las condiciones (sin agrupar),
    # junto con descripciones de consola y licencia.
    query = (
        select(
            GameDetail.id_game_detail,
            GameDetail.consola_id,
            Consoles.descripcion.label("desc_console"),
            GameDetail.licencia_id,
            Licenses.descripcion.label("desc_licence"),
            GameDetail.duracion_dias_alquiler,
            GameDetail.stock,
            GameDetail.precio,
            GameDetail.precio_descuento,
        )
        .select_from(GameDetail)
        .join(Consoles, GameDetail.consola_id == Consoles.id_console, isouter=True)
        .join(Licenses, GameDetail.licencia_id == Licenses.id_license, isouter=True)
        .where(
            GameDetail.producto_id == id_product,
            GameDetail.stock > 0,
            GameDetail.precio > 0,
        )
        .order_by(
            GameDetail.consola_id,
            GameDetail.licencia_id,
            GameDetail.duracion_dias_alquiler,
            GameDetail.precio.asc(),
        )
    )

    result = await session.execute(query)
    rows = result.all()

    # Group by (consola, desc_console, licencia, desc_licence,
    #           duracion_dias_alquiler, precio, precio_descuento)
    groups: dict[tuple, dict] = {}
    for row in rows:
        precio = row.precio or 0
        precio_descuento = row.precio_descuento or 0
        key = (
            row.consola_id,
            row.desc_console or "",
            row.licencia_id,
            row.desc_licence or "",
            row.duracion_dias_alquiler,
            precio,
            precio_descuento,
        )

        if key not in groups:
            groups[key] = {
                "pk": row.id_game_detail,
                "consola": row.consola_id,
                "desc_console": row.desc_console or "",
                "licencia": row.licencia_id,
                "desc_licence": row.desc_licence or "",
                "stock": row.stock or 0,
                "precio": precio,
                "precio_descuento": precio_descuento,
                "duracion_dias_alquiler": row.duracion_dias_alquiler,
            }
        else:
            groups[key]["stock"] += row.stock or 0

    data = list(groups.values())

    payload = {
        "message": "proceso exitoso",
        "product_id": id_product,
        "product_type": product_type,
        "data": data,
        "code": "00",
        "status": 200,
    }
    return JSONResponse(payload)


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
            "type_id": p.type_id_id,
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
            "originalPrice": row.precio_descuento,
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


@router.get("/{id_product}/related")
async def get_related_products(id_product: int, limit: int = 10, session: AsyncSession = Depends(get_session)):
    """Return products related to the given product.

    Relation is defined as sharing the same ``tipo_juego_id`` and excluding the
    product itself. Results are limited (default 10).
    """

    # Get base product
    result = await session.execute(select(Product).filter(Product.id_product == id_product))
    product = result.scalars().first()
    if not product:
        return {"data": []}

    tipo_juego_id = getattr(product, "tipo_juego_id", None)
    if not tipo_juego_id:
        return {"data": []}

    related_query = (
        select(Product)
        .where(
            Product.tipo_juego_id == tipo_juego_id,
            Product.id_product != id_product,
        )
        .order_by(Product.calification.desc())
        .limit(limit)
    )

    rel_result = await session.execute(related_query)
    related_products = rel_result.scalars().all()

    data = [
        {
            "id_product": p.id_product,
            "title": p.title,
            "description": p.description,
            "date_register": p.date_register.isoformat() if getattr(p, "date_register", None) else None,
            "image": p.image,
            "calification": p.calification,
            "puntos_venta": p.puntos_venta,
            "puede_rentarse": p.puede_rentarse,
            "destacado": p.destacado,
        }
        for p in related_products
    ]

    return {"data": data}


@router.get("/coupon/{code}")
async def validate_coupon_for_product(
    code: str,
    product_id: int,
    user_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Validate a coupon code for a specific product (optionally for a user).

    - Path: /products/coupon/{code}
    - Query params: product_id (required), user_id (optional)
    - Does **not** use JWT; caller must pass user_id explicitly
    - Coupon is considered valid when:
        * name_coupon matches code (case-sensitive)
        * product_id matches
        * (user_id is NULL or equals given user_id)
        * is_valid is True
        * expiration_date is in the future
    """

    now = datetime.utcnow()

    # user_id is optional; allow coupons that are generic (NULL) or match given user
    user_condition = or_(Coupon.user_id.is_(None), Coupon.user_id == user_id)

    query = (
        select(Coupon)
        .where(
            Coupon.name_coupon == code,
            Coupon.product_id == product_id,
            Coupon.is_valid.is_(True),
            Coupon.expiration_date > now,
            user_condition,
        )
        .limit(1)
    )

    result = await session.execute(query)
    coupon = result.scalars().first()

    if not coupon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Coupon not valid for this product or user",
        )

    return {
        "id_coupon": coupon.id_coupon,
        "name_coupon": coupon.name_coupon,
        "product_id": coupon.product_id,
        "user_id": coupon.user_id,
        "percentage_off": coupon.percentage_off,
        "points_given": coupon.points_given,
        "created_at": coupon.created_at.isoformat() if coupon.created_at else None,
        "modified_at": coupon.modified_at.isoformat() if coupon.modified_at else None,
        "expiration_date": coupon.expiration_date.isoformat() if coupon.expiration_date else None,
        "is_valid": coupon.is_valid,
    }