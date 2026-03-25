"""Business logic for the order lifecycle.

This module contains the side-effects that must fire at specific points in an
order's life:

  * on_order_created      – validate & decrement stock (atomic with the INSERT).
  * on_status_transition  – create SaleDetail on "Completado";
                            restore stock on "Cancelado".

All functions receive an open ``AsyncSession`` and add their changes to the
session WITHOUT committing.  The caller is responsible for committing (or
rolling back) the whole unit of work.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GameDetail, OrderBuy, SaleDetail

# Status string constants kept in one place.
STATUS_COMPLETADO = "Completado"
STATUS_CANCELADO = "Cancelado"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_game_detail(
    session: AsyncSession,
    product_id: int,
    id_license: int | None,
    id_console: int | None,
) -> GameDetail | None:
    """Return the GameDetail that exactly matches the product/license/console combo.

    All three columns are always used in the WHERE clause so that the lookup is
    unambiguous.  When ``id_license`` or ``id_console`` is ``None``, SQLAlchemy
    emits ``IS NULL``, which correctly targets rows where that column is null.
    """
    result = await session.execute(
        select(GameDetail).where(
            GameDetail.producto_id == product_id,
            GameDetail.licencia_id == id_license,   # None  →  IS NULL
            GameDetail.consola_id == id_console,    # None  →  IS NULL
        )
    )
    return result.scalars().first()


async def _sale_detail_exists(
    session: AsyncSession,
    product_id: int,
    user_id: int,
    combinacion_id: int | None,
) -> bool:
    """Return True if a SaleDetail already exists for this product/user/variant."""
    stmt = select(SaleDetail.id_sale_detail).where(
        SaleDetail.producto_id == product_id,
        SaleDetail.usuario_id == user_id,
    )
    if combinacion_id is not None:
        stmt = stmt.where(SaleDetail.combinacion_id == combinacion_id)
    result = await session.execute(stmt)
    return result.scalar() is not None


# ---------------------------------------------------------------------------
# Stock management
# ---------------------------------------------------------------------------


async def decrease_stock(session: AsyncSession, order: OrderBuy) -> None:
    """Validate stock availability and decrement it by 1 for the order.

    Must be called within the same database transaction as the order creation
    so that a validation failure here causes the whole operation to be rolled
    back by the caller.

    Raises:
        HTTPException 404: no GameDetail matches the order's combination.
        HTTPException 409: the matched GameDetail has insufficient stock.
    """
    game_detail = await _get_game_detail(
        session, order.product_id, order.id_license, order.id_console
    )
    if game_detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No game variant found for product {order.product_id} "
                "with the provided license/console combination."
            ),
        )
    if game_detail.stock < 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Insufficient stock for product {order.product_id}.",
        )
    game_detail.stock -= 1
    session.add(game_detail)


async def restore_stock(session: AsyncSession, order: OrderBuy) -> None:
    """Restore stock by 1 for the GameDetail that matches the order.

    Silently skips if no matching GameDetail is found so that cancellations
    on orders with an incomplete/missing variant do not crash the endpoint.
    """
    game_detail = await _get_game_detail(
        session, order.product_id, order.id_license, order.id_console
    )
    if game_detail is not None:
        game_detail.stock += 1
        session.add(game_detail)


# ---------------------------------------------------------------------------
# Sale detail
# ---------------------------------------------------------------------------


async def create_sale_detail(session: AsyncSession, order: OrderBuy) -> None:
    """Create a SaleDetail record for a completed order.

    Idempotent: if a SaleDetail already exists for this product/user/variant
    combination the function returns without creating a duplicate.  This
    guards against repeated calls when an order's status is set to
    "Completado" more than once.
    """
    game_detail = await _get_game_detail(
        session, order.product_id, order.id_license, order.id_console
    )
    combinacion_id: int | None = (
        game_detail.id_game_detail if game_detail is not None else None
    )

    if await _sale_detail_exists(session, order.product_id, order.user_id, combinacion_id):
        return  # already recorded — nothing to do

    sale = SaleDetail(
        fecha_venta=datetime.utcnow(),
        producto_id=order.product_id,
        usuario_id=order.user_id,
        combinacion_id=combinacion_id,
        cuenta_id=game_detail.cuenta_id if game_detail is not None else None,
    )
    session.add(sale)


# ---------------------------------------------------------------------------
# Public lifecycle hooks
# ---------------------------------------------------------------------------


async def on_order_created(session: AsyncSession, order: OrderBuy) -> None:
    """Side-effects to execute atomically with a new order's INSERT.

    * Validates and decrements GameDetail stock for each item in the order.

    The function only *adds* changes to the session; the caller must commit
    (or rollback on failure) the whole unit of work.
    """
    await decrease_stock(session, order)


async def on_status_transition(
    session: AsyncSession,
    order: OrderBuy,
    new_status: str,
) -> None:
    """Side-effects to execute when an order's status changes.

    * "Completado": creates a SaleDetail record (idempotent).
    * "Cancelado":  restores the GameDetail stock (only on first transition).

    *IMPORTANT*: this function reads ``order.status`` as the *previous* status
    to detect a genuine transition.  It must be called BEFORE ``order.status``
    is mutated.

    The function only *adds* changes to the session; the caller must commit
    (or rollback) the whole unit of work.
    """
    previous_status: str = order.status

    if new_status == STATUS_COMPLETADO and previous_status != STATUS_COMPLETADO:
        await create_sale_detail(session, order)

    if new_status == STATUS_CANCELADO and previous_status != STATUS_CANCELADO:
        await restore_stock(session, order)
