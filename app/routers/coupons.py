from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Coupon

router = APIRouter(prefix="/coupons", tags=["coupons"])


@router.get("/{name_coupon}")
async def get_coupon_by_name(
    name_coupon: str,
    session: AsyncSession = Depends(get_session),
):
    query = select(Coupon).where(Coupon.name_coupon == name_coupon)
    result = await session.execute(query)
    coupons = result.scalars().all()

    if not coupons:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Coupon not found",
        )

    data = [
        {
            "id_coupon": c.id_coupon,
            "name_coupon": c.name_coupon,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "modified_at": c.modified_at.isoformat() if c.modified_at else None,
            "expiration_date": c.expiration_date.isoformat() if c.expiration_date else None,
            "is_valid": c.is_valid,
            "user_id": c.user_id,
            "percentage_off": c.percentage_off,
            "points_given": c.points_given,
        }
        for c in coupons
    ]

    return {"data": data}
