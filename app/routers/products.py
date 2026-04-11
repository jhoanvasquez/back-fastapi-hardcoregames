from datetime import datetime, date, timedelta, timezone
from sys import breakpointhook

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import asyncio
from sqlalchemy import select, func, or_, cast, Integer, literal
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..models import (
    Product,
    GameDetail,
    Consoles,
    Licenses,
    Coupon,
    CouponGameDetail,
    User,
    SaleDetail,
    CouponRule,
    CouponRedemption,
)
from ..util.util_auth import get_current_user

router = APIRouter(prefix="/products", tags=["products"])

ALIAS_MAP = {
    'fifa': ['fc'],
    'cod': ['callofduty', 'callofdutyblackops', 'callofdutymw', 'callofdutywarzone'],
    'pes': ['proevolutionsoccer', 'efootball'],
    'hades2': ['hadesii', 'hadestwo', 'hades ii', 'hades two'],
    'rdr2': ['reddeadredemption2', 'reddead', 'redemption', 'rdrii', 'reddeadredemptionii', 'reddeadredemption', 'reddead2'],
    'reddead': ['reddeadredemption2', 'rdr2', 'redemption', 'rdrii', 'reddeadredemptionii', 'reddeadredemption', 'reddead2'],
    'redemption': ['reddeadredemption2', 'rdr2', 'reddead', 'rdrii', 'reddeadredemptionii', 'reddeadredemption', 'reddead2'],
    'rdrii': ['reddeadredemption2', 'rdr2', 'reddead', 'redemption', 'reddeadredemptionii', 'reddeadredemption', 'reddead2'],
    'reddeadredemptionii': ['reddeadredemption2', 'rdr2', 'reddead', 'redemption', 'rdrii', 'reddeadredemption', 'reddead2'],
    'reddeadredemption2': ['rdr2', 'reddead', 'redemption', 'rdrii', 'reddeadredemptionii', 'reddeadredemption', 'reddead2'],
    'reddeadredemption': ['reddeadredemption2', 'rdr2', 'reddead', 'redemption', 'rdrii', 'reddeadredemptionii', 'reddead2'],
    'reddead2': ['reddeadredemption2', 'rdr2', 'reddead', 'redemption', 'rdrii', 'reddeadredemptionii', 'reddeadredemption'],
    'fc26': ['FC 26'],
    'fifa26': ['FC 26'],
    'fifa 26': ['FC 26'],
}

class CartItem(BaseModel):
    """Single item in the cart used for coupon validation."""

    product_id: int
    quantity: int
    unit_price: float
    category_id: int | None = None      # used by allowed_categories coupon rule
    combination_id: int | None = None   # id_game_detail (combination pk) for coupon binding


class ValidateCouponRequest(BaseModel):
    """Payload for validating a coupon against a cart.

    The coupon code is taken from the path parameter; this body
    contains only the cart items to evaluate against the rules.
    """

    cart_items: list[CartItem]


class DiscountedItem(BaseModel):
    product_id: int
    original_unit_price: float
    discounted_unit_price: float
    quantity: int


class ValidateCouponResponse(BaseModel):
    valid: bool
    message: str
    code: str | None = None
    coupon_id: int | None = None
    total_before: float
    total_after: float
    discount_amount: float
    discounted_items: list[DiscountedItem] = []


async def _get_min_prices_for_products(session: AsyncSession, product_ids: list[int]) -> dict[int, float | None]:
    """Return a mapping product_id -> minimum base price (precio > 0).

    Only rows with stock > 0 and precio > 0 are considered.
    Use _get_min_discount_prices_for_products for the discounted price.
    """
    if not product_ids:
        return {}

    result = await session.execute(
        select(GameDetail.producto_id, func.min(GameDetail.precio))
        .where(
            GameDetail.producto_id.in_(product_ids),
            GameDetail.stock > 0,
            GameDetail.precio > 0,
        )
        .group_by(GameDetail.producto_id)
    )

    rows = result.all()
    return {producto_id: min_price for producto_id, min_price in rows}


async def _get_min_discount_prices_for_products(
    session: AsyncSession, product_ids: list[int]
) -> dict[int, float | None]:
    """Return a mapping product_id -> minimum precio_descuento (>0).

    Only rows with stock > 0 and precio_descuento > 0 are considered.
    Returns None for products with no active discount variant.
    """
    if not product_ids:
        return {}

    result = await session.execute(
        select(GameDetail.producto_id, func.min(GameDetail.precio_descuento))
        .where(
            GameDetail.producto_id.in_(product_ids),
            GameDetail.stock > 0,
            GameDetail.precio_descuento > 0,
        )
        .group_by(GameDetail.producto_id)
    )
    rows = result.all()
    return {producto_id: min_discount for producto_id, min_discount in rows}


async def _evaluate_coupon_business_rules(
    coupon: Coupon,
    user_id: int,
    cart_items: list[CartItem],
    session: AsyncSession,
) -> tuple[bool, str]:
    """Replicate Django's validate_coupon logic using database rules.

    Returns (is_valid, message), short‑circuiting on the first failure.
    """
    
    # Use a timezone-aware "now" in UTC to avoid comparing
    # offset-naive with offset-aware datetimes.
    now = datetime.now(timezone.utc)

    # Total of the cart, used by several rule types.
    cart_total = sum(item.quantity * item.unit_price for item in cart_items)
    total_quantity = sum(item.quantity for item in cart_items)

    # 1) Basic flags: active and not expired
    if not coupon.is_valid:
        return False, "El cupón no está activo."

    if coupon.expiration_date:
        # Normalize stored expiration_date to UTC and compare with aware "now".
        if coupon.expiration_date.tzinfo is None:
            exp_date = coupon.expiration_date.replace(tzinfo=timezone.utc)
        else:
            exp_date = coupon.expiration_date.astimezone(timezone.utc)

        if exp_date <= now:
            return False, "El cupón ha expirado."

    # 2) Coupon bound to a specific user
    if coupon.user_id is not None and coupon.user_id != user_id:
        return False, "Este cupón no es válido para tu cuenta."

    # 3) Coupon bound to specific GameDetails (M2M) — at least one linked
    #    item must be present in the cart. Empty = applies to all.
    res_gd = await session.execute(
        select(CouponGameDetail.gamedetail_id)
        .where(CouponGameDetail.coupon_id == coupon.id_coupon)
    )
    coupon_game_detail_ids = {row[0] for row in res_gd.all()}
    if coupon_game_detail_ids:
        # Fetch allowed GameDetail attributes for the coupon
        res_products = await session.execute(
            select(
                GameDetail.id_game_detail,
                GameDetail.licencia_id,
                GameDetail.consola_id,
                GameDetail.duracion_dias_alquiler
            ).where(GameDetail.id_game_detail.in_(coupon_game_detail_ids))
        )
        allowed_combinations = {
            (row.licencia_id, row.consola_id, row.duracion_dias_alquiler)
            for row in res_products.all()
        }

        # For each cart item, fetch its GameDetail and compare attributes
        found_match = False
        for item in cart_items:
            # If combination_id is provided, use it; else, skip
            if item.product_id is not None:
                res_cart_gd = await session.execute(
                    select(
                        GameDetail.licencia_id,
                        GameDetail.consola_id,
                        GameDetail.duracion_dias_alquiler
                    ).where(GameDetail.id_game_detail == item.product_id)
                )
                cart_gd = res_cart_gd.first()
                if cart_gd:
                    cart_tuple = (cart_gd.licencia_id, cart_gd.consola_id, cart_gd.duracion_dias_alquiler)
                    if cart_tuple in allowed_combinations:
                        found_match = True
                        break
        if not found_match:
            return False, "El cupón no aplica a los productos del carrito."

    # 4) Evaluate rule rows attached to the coupon
    result_rules = await session.execute(
        select(CouponRule).where(CouponRule.coupon_id == coupon.id_coupon)
    )
    rules = result_rules.scalars().all()

    for rule in rules:
        rt = (rule.rule_type or "").lower()
        op = (rule.operator or "").lower()
        value = rule.value if rule.value is not None else {}

        # --- min_order_amount -----------------------------------------
        if rt == "min_order_amount":
            v = value if isinstance(value, dict) else {}
            amount = v.get("amount", value) if isinstance(value, dict) else value

            if op == "gte":
                if cart_total >= amount:
                    continue
                return False, f"El monto mínimo de la orden debe ser {amount}."

            if op == "between":
                min_val = v.get("min", 0)
                max_val = v.get("max", float("inf"))
                if min_val <= cart_total <= max_val:
                    continue
                return False, f"El monto de la orden debe estar entre {min_val} y {max_val}."

        # --- max_order_amount -----------------------------------------
        elif rt == "max_order_amount":
            amount = value if isinstance(value, (int, float)) else value.get("amount", float("inf"))

            if op == "lte":
                if cart_total <= amount:
                    continue
                return False, f"El monto máximo de la orden es {amount}."

            if op == "between":
                min_val = value.get("min", 0)
                max_val = value.get("max", float("inf"))
                if min_val <= cart_total <= max_val:
                    continue
                return False, f"El monto de la orden debe estar entre {min_val} y {max_val}."

        # --- min_item_quantity ----------------------------------------
        elif rt == "min_item_quantity":
            v = value if isinstance(value, dict) else {}
            min_qty = v.get("quantity", value) if isinstance(value, dict) else value
            
            if op == "gte":
                if total_quantity >= min_qty:
                    continue
                return False, f"Se requieren al menos {min_qty} ítems en el carrito."

            if op == "eq":
                if total_quantity == min_qty:
                    continue
                return False, f"Se requieren exactamente {min_qty} ítems en el carrito."

            if op == "between":
                max_qty = v.get("max", float("inf"))
                if min_qty <= total_quantity <= max_qty:
                    continue
                return False, f"La cantidad de ítems debe estar entre {min_qty} y {max_qty}."

        # --- allowed_categories ---------------------------------------
        elif rt == "allowed_categories":
            v = value if isinstance(value, dict) else {}
            allowed = v.get("categories", [])
            cart_categories = {item.category_id for item in cart_items if item.category_id is not None}

            if op == "in":
                if cart_categories & set(allowed):
                    continue
                return False, "Ningún ítem del carrito pertenece a las categorías permitidas."

        # --- day_of_week ----------------------------------------------
        elif rt == "day_of_week":
            v = value if isinstance(value, dict) else {}
            allowed_days = v.get("days", [])  # 0=Monday … 6=Sunday
            current_day = now.weekday()

            if op == "in":
                if current_day in allowed_days:
                    continue
                day_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
                allowed_names = ", ".join(day_names[d] for d in allowed_days if 0 <= d <= 6)
                return False, f"El cupón solo es válido los siguientes días: {allowed_names}."

        # --- first_purchase_only --------------------------------------
        elif rt == "first_purchase_only":
            res_count = await session.execute(
                select(func.count(SaleDetail.id_sale_detail)).where(
                    SaleDetail.usuario_id == user_id
                )
            )
            sale_count = res_count.scalar() or 0
            if sale_count == 0:
                continue
            return False, "Este cupón es válido solo para la primera compra."

        # --- usage_limit_total ----------------------------------------
        elif rt == "usage_limit_total":
            limit = value.get("limit", 0) if isinstance(value, dict) else value
            if limit is not None:
                res_count = await session.execute(
                    select(func.count(CouponRedemption.id)).where(
                        CouponRedemption.coupon_id == coupon.id_coupon
                    )
                )
                total_used = res_count.scalar() or 0
                if op in ("lte", "eq"):
                    if total_used < int(limit):
                        continue
                return False, "El cupón ha alcanzado el límite máximo de usos."

        # --- usage_limit_per_user -------------------------------------
        elif rt == "usage_limit_per_user":
            limit = value.get("limit", 1) if isinstance(value, dict) else value
            if limit is not None:
                res_count = await session.execute(
                    select(func.count(CouponRedemption.id)).where(
                        CouponRedemption.coupon_id == coupon.id_coupon,
                        CouponRedemption.user_id == user_id,
                    )
                )
                user_used = res_count.scalar() or 0
                if op in ("lte", "eq"):
                    if user_used < int(limit):
                        continue
                return False, "Has alcanzado el límite de usos de este cupón."

        # Unknown / unhandled rule type — pass silently (matches Django fallback)

    return True, "Cupón válido."


@router.get("/")
async def list_products(
    search: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    query = select(Product).options(selectinload(Product.consoles)).order_by(Product.id_product)

    if search:
        def normalize(s):
            from unidecode import unidecode
            return unidecode(s).lower().replace(' ', '')
        
        search_norm = normalize(search)
        title_expr = func.replace(func.unaccent(func.lower(Product.title)), ' ', '')

        # If search matches an alias, search for all mapped aliases
        if search_norm in ALIAS_MAP:
            alias_patterns = [f"%{alias}%" for alias in ALIAS_MAP[search_norm]]
            conditions = [title_expr.ilike(pat) for pat in alias_patterns]
            query = query.where(or_(*conditions))
        else:
            pattern = f"%{search_norm}%"
            query = query.where(title_expr.ilike(pattern))

    result = await session.execute(query)
    products = result.scalars().all()
    product_ids = [p.id_product for p in products]
    min_prices = await _get_min_prices_for_products(session, product_ids)
    min_discount_prices = await _get_min_discount_prices_for_products(session, product_ids)

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
            "price": min_prices.get(p.id_product),
            "price_discount": min_discount_prices.get(p.id_product),
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
async def get_products(offset: int = 0, limit: int = 10, session: AsyncSession = Depends(get_session)):
    """Paginate products using classic offset/limit.

    - Query params:
        * offset: number of items to skip (default 0)
        * limit: max number of items to return (default 10)
    """

    query = select(Product).order_by(Product.id_product)
    if offset:
        query = query.offset(offset)
    query = query.limit(limit)
    result = await session.execute(query)
    products = result.scalars().all()
    product_ids = [p.id_product for p in products]
    min_prices = await _get_min_prices_for_products(session, product_ids)
    min_discount_prices = await _get_min_discount_prices_for_products(session, product_ids)

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
            "price": min_prices.get(p.id_product),
            "price_discount": min_discount_prices.get(p.id_product),
            "consoles": [
                {"id_console": c.id_console}
                for c in getattr(p, "consoles", []) or []
            ],
        }
        for p in products
    ]
    return {"data": data}


@router.get("/favorites")
async def get_favorites(limit: int = 20, offset: int = 0, session: AsyncSession = Depends(get_session)):
    """
    Obtener productos marcados como favoritos (destacado=True) ordenados por calification (desc).
    """
    query = select(Product).where(Product.destacado.is_(True)).order_by(Product.calification.desc())
    if offset:
        query = query.offset(offset)
    query = query.limit(limit)
    result = await session.execute(query)
    products = result.scalars().all()
    product_ids = [p.id_product for p in products]
    min_prices = await _get_min_prices_for_products(session, product_ids)
    min_discount_prices = await _get_min_discount_prices_for_products(session, product_ids)

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
            "price": min_prices.get(p.id_product),
            "price_discount": min_discount_prices.get(p.id_product),
        }
        for p in products
    ]

    return {"data": data}


@router.get("/week-offers")
async def get_week_offers(
    offset: int = 0,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
):
    """Return products that have active coupon offers created in the last week.

    A product is considered a "week offer" when there exists at least one
    Coupon for that product such that:

    - percentage_off > 0
    - is_valid is True
    - expiration_date > now
    - created_at >= now - 7 days

    Results are ordered by the coupon creation date (newest first) and
    paginated with offset/limit. Each product includes the computed
    ``price`` field (minimum non-zero GameDetail.precio).
    """

    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    query = (
        select(Product)
        .join(Coupon, Coupon.product_id == Product.id_product)
        .where(
            Coupon.percentage_off > 0,
            Coupon.is_valid.is_(True),
            Coupon.expiration_date > now,
            Coupon.created_at >= week_ago,
        )
        .order_by(Coupon.created_at.desc())
    )

    if offset:
        query = query.offset(offset)
    query = query.limit(limit)

    result = await session.execute(query)
    products = result.scalars().unique().all()
    product_ids = [p.id_product for p in products]
    min_prices = await _get_min_prices_for_products(session, product_ids)
    min_discount_prices = await _get_min_discount_prices_for_products(session, product_ids)

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
            "price": min_prices.get(p.id_product),
            "price_discount": min_discount_prices.get(p.id_product),
        }
        for p in products
    ]

    return {"data": data}


@router.get("/by-type/{type_id}")
async def get_products_by_type(
    type_id: int,
    session: AsyncSession = Depends(get_session),
    limit: int = 20,
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
        .limit(limit)
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
    limit: int = 20,
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
        .limit(limit)
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
    limit: int = 20,
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
        .limit(limit)
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


@router.get("/filter")
async def filter_products(
    type_id: int | None = None,
    console_id: int | None = None,
    game_type_id: int | None = None,
    offset: int = 0,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
):
    """Filter products by optional type, console and game type.

    - Query params (all optional):
        * type_id: filters by Product.type_id_id
        * console_id: filters by Consoles.id_console
        * game_type_id: filters by Product.tipo_juego_id
    If any param is omitted or null, that filter is not applied.
    Supports offset/limit pagination.
    """

    query = select(Product).options(selectinload(Product.consoles))
    conditions = []

    if type_id is not None:
        conditions.append(cast(Product.type_id_id, Integer) == type_id)

    if game_type_id is not None:
        conditions.append(cast(Product.tipo_juego_id, Integer) == game_type_id)

    if console_id is not None:
        query = query.join(Product.consoles)
        conditions.append(Consoles.id_console == console_id)

    if conditions:
        query = query.where(*conditions)

    query = query.order_by(Product.id_product)
    if offset:
        query = query.offset(offset)
    query = query.limit(limit)

    result = await session.execute(query)
    products = result.scalars().all()
    product_ids = [p.id_product for p in products]
    min_prices = await _get_min_prices_for_products(session, product_ids)
    min_discount_prices = await _get_min_discount_prices_for_products(session, product_ids)

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
            "price": min_prices.get(p.id_product),
            "price_discount": min_discount_prices.get(p.id_product),
            "consoles": [
                {"id_console": c.id_console}
                for c in getattr(p, "consoles", []) or []
            ],
        }
        for p in products
    ]

    return {"data": data}


@router.get("/by-date")
async def get_products_from_date(
    from_date: date | None = Query(default=None),
    date_param: date | None = Query(default=None, alias="date"),
    offset: int = 0,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
):
    """Filter products by registration date from a given day until today.

    - Query params:
        * from_date or date: starting date (YYYY-MM-DD) — either name is accepted
        * offset: number of items to skip (default 0)
        * limit: max number of items to return (default 20)

    Returns products whose ``date_register`` is between the given date
    and today's date (inclusive).
    """

    resolved_date = from_date or date_param
    if resolved_date is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query parameter 'from_date' (or 'date') is required.",
        )

    today = datetime.utcnow().date()
    query = (
        select(Product)
        .options(selectinload(Product.consoles))
        .where(
            Product.date_register >= resolved_date,
            Product.date_register <= today,
        )
        .order_by(Product.date_register.desc(), Product.id_product)
    )

    if offset:
        query = query.offset(offset)
    query = query.limit(limit)

    result = await session.execute(query)
    products = result.scalars().all()
    product_ids = [p.id_product for p in products]
    min_prices = await _get_min_prices_for_products(session, product_ids)
    min_discount_prices = await _get_min_discount_prices_for_products(session, product_ids)

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
            "price": min_prices.get(p.id_product),
            "price_discount": min_discount_prices.get(p.id_product),
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

    def normalize(s):
        from unidecode import unidecode
        return unidecode(s).lower().replace(' ', '')

    search_norm = normalize(q)
    title_expr = func.replace(func.unaccent(func.lower(Product.title)), ' ', '')

    if search_norm in ALIAS_MAP:
        alias_patterns = [f"%{alias}%" for alias in ALIAS_MAP[search_norm]]
        conditions = [title_expr.ilike(pat) for pat in alias_patterns]
        base = select(Product).where(or_(*conditions)).limit(limit)
    else:
        pattern = f"%{search_norm}%"
        base = select(Product).where(title_expr.ilike(pattern)).limit(limit)

    if use_trgm:
        base = base.order_by(func.similarity(Product.title, q).desc())

    result = await session.execute(base)
    products = result.scalars().all()
    product_ids = [p.id_product for p in products]
    min_prices = await _get_min_prices_for_products(session, product_ids)
    min_discount_prices = await _get_min_discount_prices_for_products(session, product_ids)

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
            "price": min_prices.get(p.id_product),
            "price_discount": min_discount_prices.get(p.id_product)
        }
        for p in products
    ]
    return {"data": data}


@router.get("/most-sold")
async def get_most_sold_products(
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """Return products ordered by number of sales (most sold first).

    Counts how many orders exist in ``OrderBuy`` for each product and
    returns products sorted by that count in descending order. Supports
    offset/limit pagination and includes the computed ``price`` field.
    """

    query = (
        select(Product, func.count(SaleDetail.id_sale_detail).label("sales_count"))
        .join(SaleDetail, SaleDetail.producto_id == Product.id_product)
        .group_by(Product.id_product)
        .order_by(func.count(SaleDetail.id_sale_detail).desc())
    )

    if offset:
        query = query.offset(offset)
    query = query.limit(limit)

    result = await session.execute(query)
    rows = result.all()
    products = [row[0] for row in rows]
    sales_counts = {row[0].id_product: row[1] for row in rows}
    product_ids = [p.id_product for p in products]
    min_prices = await _get_min_prices_for_products(session, product_ids)
    min_discount_prices = await _get_min_discount_prices_for_products(session, product_ids)

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
            "price": min_prices.get(p.id_product),
            "price_discount": min_discount_prices.get(p.id_product),
            "sales_count": int(sales_counts.get(p.id_product, 0)),
        }
        for p in products
    ]

    return {"data": data}


@router.get("/{id_product}")
async def get_product_by_id(id_product: int, session: AsyncSession = Depends(get_session)):

    result = await session.execute(
        select(Product)
        .options(selectinload(Product.consoles))
        .filter(Product.id_product == id_product)
    )
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
        "consoles": [
            {"id_console": c.id_console}
            for c in getattr(product, "consoles", []) or []
        ],
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


@router.post("/coupon/{code}", response_model=ValidateCouponResponse)
async def validate_coupon_for_product(
    code: str,
    payload: ValidateCouponRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Validate a coupon code for the current user's cart.

    - Path: /products/coupon/{code}
    - Body: cart_items with product, quantity and unit_price
    - Auth: JWT via get_current_user

    Implements the full Django-side validate_coupon logic:
    * Basic flags (active, not expired)
    * User binding (coupon.user_id)
    * Product binding (coupon.product_id present in cart)
    * Rule evaluation via products_couponrule and products_couponredemption
    If valid, returns totals and per-product prices with coupon applied.
    """

    if not payload.cart_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El carrito está vacío.",
        )

    now = datetime.now(timezone.utc)

    # Fetch coupon by code applying early filters:
    # - not expired
    # - user binding: coupon.user_id IS NULL (public) OR matches the requester
    result = await session.execute(
        select(Coupon).where(
            func.lower(Coupon.name_coupon) == code.lower(),
            Coupon.expiration_date > now,
            Coupon.is_valid.is_(True),
            or_(
                Coupon.user_id.is_(None),
                Coupon.user_id == current_user.id,
            ),
        ).limit(1)
    )
    coupon = result.scalars().first()

    if not coupon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cupón no encontrado o no activo.",
        )

    is_valid, message = await _evaluate_coupon_business_rules(
        coupon=coupon,
        user_id=current_user.id,
        cart_items=payload.cart_items,
        session=session,
    )

    # Compute cart totals and, if applicable, discounted prices.
    total_before = sum(
        item.quantity * item.unit_price for item in payload.cart_items
    )
    total_after = total_before
    discounted_items: list[DiscountedItem] = []

    if is_valid and coupon.percentage_off and coupon.percentage_off > 0:
        discount_factor = (100 - coupon.percentage_off) / 100.0
        discounted_total = 0.0

        # Resolve which items are covered by this coupon's game_details M2M.
        # Empty set means the discount applies to all cart items.
        res_gd = await session.execute(
            select(CouponGameDetail.gamedetail_id)
            .where(CouponGameDetail.coupon_id == coupon.id_coupon)
        )
        coupon_game_detail_ids = {row[0] for row in res_gd.all()}

        for item in payload.cart_items:
            if not coupon_game_detail_ids:
                # No restriction — discount applies to everything
                applies = True
            elif item.combination_id is not None:
                # Tier 1: explicit combination_id matches a linked gamedetail_id
                applies = item.combination_id in coupon_game_detail_ids
            else:
                # Tier 2: client sends gamedetail_id as product_id
                applies = item.product_id in coupon_game_detail_ids
            # NOTE: tier-3 (gamedetail→producto_id resolution) is intentionally
            # NOT used here to avoid discounting unrelated items.

            if applies:
                discounted_unit_price = item.unit_price * discount_factor
                discounted_line_total = discounted_unit_price * item.quantity
                discounted_total += discounted_line_total

                discounted_items.append(
                    DiscountedItem(
                        product_id=item.product_id,
                        original_unit_price=item.unit_price,
                        discounted_unit_price=discounted_unit_price,
                        quantity=item.quantity,
                    )
                )
            else:
                discounted_total += item.unit_price * item.quantity

        total_after = discounted_total  # moved outside the loop

    discount_amount = max(total_before - total_after, 0.0)

    return ValidateCouponResponse(
        valid=is_valid,
        message=message,
        code=coupon.name_coupon,
        coupon_id=coupon.id_coupon,
        total_before=total_before,
        total_after=total_after if is_valid else total_before,
        discount_amount=discount_amount if is_valid else 0.0,
        discounted_items=discounted_items if is_valid else [],
    )