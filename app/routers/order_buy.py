from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_session
from app.models import GameDetail, Product, User, OrderBuy
from app.repositories.order_buy import OrderBuyRepository
from app.util.util_auth import get_current_user

router = APIRouter(prefix="/order-buy", tags=["order-buy"])


class OrderBuyCreate(BaseModel):
    product_id: int
    status: str | None = None


class ProductInfo(BaseModel):
    id_game_detail: int
    id_product: int
    title: str
    description: str
    image: str | None = None


class OrderBuyRead(BaseModel):
    id_order: int
    user_id: int
    product_id: int
    status: str
    file_path: str | None = None
    product: ProductInfo | None = None

    class Config:
        orm_mode = True


@router.get("/admin", response_model=list[OrderBuyRead])
async def list_all_orders_paginated(
    page: int = 1,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return all orders, 20 per page, only for superusers.

    Uses JWT session token via get_current_user and checks current_user.is_superuser.
    """

    if not bool(getattr(current_user, "is_superuser", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to list all orders",
        )

    page_size = 20
    if page < 1:
        page = 1
    offset = (page - 1) * page_size

    result = await session.execute(
        select(OrderBuy, GameDetail, Product)
        .join(GameDetail, OrderBuy.product_id == GameDetail.id_game_detail)
        .join(Product, GameDetail.producto_id == Product.id_product)
        .order_by(OrderBuy.id_order.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = result.all()

    return [
        {
            "id_order": order.id_order,
            "user_id": order.user_id,
            "product_id": order.product_id,
            "status": order.status,
            "file_path": order.file_path,
            "product": {
                "id_game_detail": gd.id_game_detail,
                "id_product": p.id_product,
                "title": p.title,
                "description": p.description,
                "image": p.image,
            },
        }
        for order, gd, p in rows
    ]


@router.get("/", response_model=list[OrderBuyRead])
async def list_orders(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(OrderBuy, GameDetail, Product)
        .join(GameDetail, OrderBuy.product_id == GameDetail.id_game_detail)
        .join(Product, GameDetail.producto_id == Product.id_product)
        .where(OrderBuy.user_id == current_user.id)
    )
    rows = result.all()

    return [
        {
            "id_order": order.id_order,
            "user_id": order.user_id,
            "product_id": order.product_id,
            "status": order.status,
            "file_path": order.file_path,
            "product": {
                "id_game_detail": gd.id_game_detail,
                "id_product": p.id_product,
                "title": p.title,
                "description": p.description,
                "image": p.image,
            },
        }
        for order, gd, p in rows
    ]


@router.get("/{order_id}", response_model=OrderBuyRead)
async def get_order(order_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(OrderBuy, GameDetail, Product)
        .join(GameDetail, OrderBuy.product_id == GameDetail.id_game_detail)
        .join(Product, GameDetail.producto_id == Product.id_product)
        .where(OrderBuy.id_order == order_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    order, gd, p = row
    return {
        "id_order": order.id_order,
        "user_id": order.user_id,
        "product_id": order.product_id,
        "status": order.status,
        "file_path": order.file_path,
        "product": {
            "id_game_detail": gd.id_game_detail,
            "id_product": p.id_product,
            "title": p.title,
            "description": p.description,
            "image": p.image,
        },
    }


@router.post("/", response_model=OrderBuyRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    product_id: int = Form(...),
    status_value: str | None = Form(None, alias="status"),
    file: UploadFile | None = File(None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Ensure game detail exists (represents a specific product combination)
    game_detail = await session.get(GameDetail, product_id)
    if not game_detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game detail not found")

    # For now we only store the filename as file_path; real storage can be added later
    file_path = file.filename if file is not None else None

    order = await OrderBuyRepository.create(
        session=session,
        user_id=current_user.id,
        product_id=product_id,
        status=status_value or "pending",
        file_path=file_path,
    )
    # Fetch the associated product explicitly to avoid lazy loads
    product = await session.get(Product, game_detail.producto_id)

    return {
        "id_order": order.id_order,
        "user_id": order.user_id,
        "product_id": order.product_id,
        "status": order.status,
        "file_path": order.file_path,
        "product": {
            "id_game_detail": game_detail.id_game_detail,
            "id_product": product.id_product if product else None,
            "title": product.title if product else "",
            "description": product.description if product else "",
            "image": product.image if product else None,
        },
    }


@router.put("/{order_id}", response_model=OrderBuyRead)
async def update_order(
    order_id: int,
    status_value: str | None = Form(None, alias="status"),
    file: UploadFile | None = File(None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    order = await OrderBuyRepository.get_by_id(session, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if order.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this order")

    file_path = file.filename if file is not None else None

    updated = await OrderBuyRepository.update(
        session=session,
        order=order,
        status=status_value,
        file_path=file_path,
    )
    game_detail = await session.get(GameDetail, updated.product_id)
    product = await session.get(Product, game_detail.producto_id) if game_detail else None

    return {
        "id_order": updated.id_order,
        "user_id": updated.user_id,
        "product_id": updated.product_id,
        "status": updated.status,
        "file_path": updated.file_path,
        "product": {
            "id_game_detail": game_detail.id_game_detail if game_detail else None,
            "id_product": product.id_product if product else None,
            "title": product.title if product else "",
            "description": product.description if product else "",
            "image": product.image if product else None,
        } if game_detail else None,
    }


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    order = await OrderBuyRepository.get_by_id(session, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if order.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this order")

    await OrderBuyRepository.delete(session, order)
    return None
