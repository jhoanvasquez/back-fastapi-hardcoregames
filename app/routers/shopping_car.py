from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ShoppingCar, User, GameDetail
from app.util.util_auth import get_current_user

router = APIRouter(prefix="/shopping-car", tags=["shopping-car"])


class ShoppingCarCreate(BaseModel):
    product_id: int
    estado: bool | None = True


class ShoppingCarUpdate(BaseModel):
    estado: bool


class ShoppingCarRead(BaseModel):
    id_shopping_car: int
    user_id: int
    product_id: int
    estado: bool
    product_price: int | None = None

    class Config:
        orm_mode = True


@router.get("/", response_model=list[ShoppingCarRead])
async def list_shopping_car(
    state: bool | None = None,
    user_id: int | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    query = (
        select(ShoppingCar, GameDetail.precio)
        .join(GameDetail, ShoppingCar.product_id == GameDetail.id_game_detail)
    )

    # if user_id is not provided, default to current user
    effective_user_id = user_id if user_id is not None else current_user.id
    query = query.where(ShoppingCar.user_id == effective_user_id)

    if state is not None:
        query = query.where(ShoppingCar.estado == state)

    result = await session.execute(query)
    rows = result.all()

    return [
        ShoppingCarRead(
            id_shopping_car=item.id_shopping_car,
            user_id=item.user_id,
            product_id=item.product_id,
            estado=item.estado,
            product_price=price,
        )
        for item, price in rows
    ]


@router.get("/{shopping_car_id}", response_model=ShoppingCarRead)
async def get_shopping_car_item(
    shopping_car_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(ShoppingCar, GameDetail.precio)
        .join(GameDetail, ShoppingCar.product_id == GameDetail.id_game_detail)
        .where(ShoppingCar.id_shopping_car == shopping_car_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    item, price = row
    if item.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    return ShoppingCarRead(
        id_shopping_car=item.id_shopping_car,
        user_id=item.user_id,
        product_id=item.product_id,
        estado=item.estado,
        product_price=price,
    )


@router.post("/", response_model=ShoppingCarRead, status_code=status.HTTP_201_CREATED)
async def create_shopping_car_item(
    payload: ShoppingCarCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    item = ShoppingCar(
        user_id=current_user.id,
        product_id=payload.product_id,
        estado=payload.estado if payload.estado is not None else True,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)

    price_result = await session.execute(
        select(GameDetail.precio).where(GameDetail.id_game_detail == item.product_id)
    )
    price = price_result.scalar()

    return ShoppingCarRead(
        id_shopping_car=item.id_shopping_car,
        user_id=item.user_id,
        product_id=item.product_id,
        estado=item.estado,
        product_price=price,
    )


@router.put("/{product_id}", response_model=ShoppingCarRead)
async def update_shopping_car_item(
    product_id: int,
    payload: ShoppingCarUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(ShoppingCar).where(
            ShoppingCar.user_id == current_user.id,
            ShoppingCar.product_id == product_id,
        )
    )
    item = result.scalars().first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    item.estado = payload.estado
    await session.commit()
    await session.refresh(item)

    price_result = await session.execute(
        select(GameDetail.precio).where(GameDetail.id_game_detail == item.product_id)
    )
    price = price_result.scalar()

    return ShoppingCarRead(
        id_shopping_car=item.id_shopping_car,
        user_id=item.user_id,
        product_id=item.product_id,
        estado=item.estado,
        product_price=price,
    )


@router.delete("/{shopping_car_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shopping_car_item(
    shopping_car_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    item = await session.get(ShoppingCar, shopping_car_id)
    if not item or item.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    await session.delete(item)
    await session.commit()
    return None
