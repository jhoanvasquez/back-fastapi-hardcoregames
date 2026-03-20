from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, conint

from ..database import get_session
from ..models import User, UserCustomized
from ..util.util_auth import get_current_user

router = APIRouter(prefix="/users", tags=["user-points"])


class PointsResponse(BaseModel):
    points: int
    balance_exchange: int


class ExchangePointsRequest(BaseModel):
    # Number of points the user wants to convert to balance.
    points_to_exchange: conint(gt=0)


class ExchangePointsResponse(BaseModel):
    points_before: int
    points_after: int
    balance_before: int
    balance_after: int
    exchanged_points: int
    exchanged_amount_cop: int


async def _get_or_create_user_customized(
    session: AsyncSession, current_user: User
) -> UserCustomized:
    result = await session.execute(
        select(UserCustomized).where(UserCustomized.user_id == current_user.id)
    )
    profile = result.scalars().first()

    if profile is None:
        # Create a new profile with 0 points and 0 balance
        profile = UserCustomized(user_id=current_user.id, puntos=0, balance_exchange=0)
        session.add(profile)
        await session.flush()

    return profile


@router.get("/me/points", response_model=PointsResponse)
async def get_my_points(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return current user's available points and balance_exchange."""

    print("current_user.id --->", current_user.id)
    result = await session.execute(
        select(UserCustomized).where(UserCustomized.user_id == current_user.id)
    )
    profile = result.scalars().first()

    if profile is None:
        return PointsResponse(points=0, balance_exchange=0)

    puntos = int(profile.puntos or 0)
    balance = int(profile.balance_exchange or 0)
    return PointsResponse(points=puntos, balance_exchange=balance)


@router.post("/me/exchange-points", response_model=ExchangePointsResponse)
async def exchange_points_for_balance(
    payload: ExchangePointsRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Exchange loyalty points for balance_exchange.

    Conversion rate: **1 point = 0.5 COP**.

    The amount credited to `balance_exchange` is stored as an integer COP,
    so the calculated value is truncated to an integer (e.g. 3 points -> 1 COP).
    """

    profile = await _get_or_create_user_customized(session, current_user)

    if profile.puntos < payload.points_to_exchange:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tienes suficientes puntos para canjear.",
        )

    points_before = int(profile.puntos or 0)
    balance_before = int(profile.balance_exchange or 0)

    exchanged_points = int(payload.points_to_exchange)
    exchanged_amount_cop = int(exchanged_points * 0.5)

    # Update profile
    profile.puntos = points_before - exchanged_points
    profile.balance_exchange = balance_before + exchanged_amount_cop

    await session.commit()
    await session.refresh(profile)

    return ExchangePointsResponse(
        points_before=points_before,
        points_after=int(profile.puntos or 0),
        balance_before=balance_before,
        balance_after=int(profile.balance_exchange or 0),
        exchanged_points=exchanged_points,
        exchanged_amount_cop=exchanged_amount_cop,
    )
