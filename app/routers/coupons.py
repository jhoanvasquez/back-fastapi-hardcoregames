from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Coupon

router = APIRouter(prefix="/coupons", tags=["coupons"])


def _serialize_coupon(c: Coupon) -> dict:
    return {
        "id_coupon": c.id_coupon,
        "name_coupon": c.name_coupon,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "modified_at": c.modified_at.isoformat() if c.modified_at else None,
        "expiration_date": c.expiration_date.isoformat() if c.expiration_date else None,
        "is_valid": c.is_valid,
        "user_id": c.user_id,
        "percentage_off": c.percentage_off,
        "points_given": c.points_given,
        "product_id": c.product_id,
    }


@router.get("/{coupon_id}")
async def get_coupon_by_id(
    coupon_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get coupon by its id (no user filter)."""

    result = await session.execute(
        select(Coupon).where(Coupon.id_coupon == coupon_id)
    )
    coupon = result.scalars().first()

    if not coupon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Coupon not found",
        )

    return {"data": [_serialize_coupon(coupon)]}


@router.get("/{coupon_id}/{user_id}")
async def get_coupon_by_id_and_user(
    coupon_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get coupon by id and user_id, for URLs like /coupons/123/5.

    If you want user_id to behave as "optional", call /coupons/{coupon_id}
    without the second path segment.
    """

    result = await session.execute(
        select(Coupon).where(
            Coupon.id_coupon == coupon_id,
            Coupon.user_id == user_id,
        )
    )
    coupon = result.scalars().first()

    if not coupon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Coupon not found for this user",
        )

    return {"data": [_serialize_coupon(coupon)]}
