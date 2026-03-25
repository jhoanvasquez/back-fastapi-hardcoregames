from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_session
from app.models import Product, User, OrderBuy
from app.repositories.order_buy import OrderBuyRepository
from app.services.order_buy import on_order_created, on_status_transition
from app.util.util_auth import get_current_user
from app.util.supabase_storage import upload_invoice_file, SupabaseNotConfiguredError

router = APIRouter(prefix="/order-buy", tags=["order-buy"])


class OrderBuyCreate(BaseModel):
    product_id: int
    status: str | None = None


class ProductInfo(BaseModel):
    # Optional: legacy field, no longer populated now that
    # orders link directly to Product instead of GameDetail
    id_game_detail: int | None = None
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
    description_order: str | None = None
    product: ProductInfo | None = None

    class Config:
        orm_mode = True


class OrderBuyPatch(BaseModel):
    status: str | None = None
    description_order: str | None = None


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
        select(OrderBuy, Product)
        .join(Product, OrderBuy.product_id == Product.id_product)
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
            "description_order": order.description_order,
            "product": {
                "id_product": p.id_product,
                "title": p.title,
                "description": p.description,
                "image": p.image,
            },
        }
        for order, p in rows
    ]


@router.get("/", response_model=list[OrderBuyRead])
async def list_orders(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(OrderBuy, Product)
        .join(Product, OrderBuy.product_id == Product.id_product)
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
            "description_order": order.description_order,
            "product": {
                "id_product": p.id_product,
                "title": p.title,
                "description": p.description,
                "image": p.image,
            },
        }
        for order, p in rows
    ]


@router.get("/{order_id}", response_model=OrderBuyRead)
async def get_order(order_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(OrderBuy, Product)
        .join(Product, OrderBuy.product_id == Product.id_product)
        .where(OrderBuy.id_order == order_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    order, p = row
    return {
        "id_order": order.id_order,
        "user_id": order.user_id,
        "product_id": order.product_id,
        "status": order.status,
        "file_path": order.file_path,
        "description_order": order.description_order,
        "product": {
            "id_product": p.id_product,
            "title": p.title,
            "description": p.description,
            "image": p.image,
        },
    }


@router.post("/", response_model=OrderBuyRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    product_id: int = Form(...),
    id_license: int | None = Form(None),
    id_console: int | None = Form(None),
    status_value: str | None = Form(None, alias="status"),
    file: UploadFile | None = File(None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Ensure product exists
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    # Upload invoice file to Supabase Storage (if provided)
    file_path = None
    if file is not None:
        object_name = f"orders/{current_user.id}/{int(datetime.utcnow().timestamp())}_{file.filename}"
        try:
            file_path = await upload_invoice_file(file, object_name)
        except SupabaseNotConfiguredError:
            # Fallback: keep just the original filename if Supabase is not configured
            file_path = file.filename

    # Create the order inside the current session transaction (no commit yet).
    order = await OrderBuyRepository.create_no_commit(
        session=session,
        user_id=current_user.id,
        product_id=product_id,
        status=status_value or "pending",
        file_path=file_path,
        id_license=id_license,
        id_console=id_console,
    )

    # Validate and decrement stock — raises HTTPException on failure, which
    # causes the session to close without committing (implicit rollback).
    await on_order_created(session, order)

    # Commit order INSERT + stock decrement atomically.
    await session.commit()
    await session.refresh(order)

    return {
        "id_order": order.id_order,
        "user_id": order.user_id,
        "product_id": order.product_id,
        "status": order.status,
        "file_path": order.file_path,
        "description_order": order.description_order,
        "product": {
            "id_product": product.id_product,
            "title": product.title,
            "description": product.description,
            "image": product.image,
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

    file_path = None
    if file is not None:
        object_name = f"orders/{current_user.id}/{int(datetime.utcnow().timestamp())}_{file.filename}"
        try:
            file_path = await upload_invoice_file(file, object_name)
        except SupabaseNotConfiguredError:
            file_path = file.filename

    # Run lifecycle side-effects BEFORE mutating order.status so the service
    # can read the previous status to detect genuine transitions.
    if status_value is not None:
        await on_status_transition(session, order, status_value)

    updated = await OrderBuyRepository.update(
        session=session,
        order=order,
        status=status_value,
        file_path=file_path,
    )
    product = await session.get(Product, updated.product_id)

    return {
        "id_order": updated.id_order,
        "user_id": updated.user_id,
        "product_id": updated.product_id,
        "status": updated.status,
        "file_path": updated.file_path,
        "product": {
            "id_product": product.id_product if product else None,
            "title": product.title if product else "",
            "description": product.description if product else "",
            "image": product.image if product else None,
        },
    }


@router.patch("/{order_id}", response_model=OrderBuyRead)
async def patch_order(
    order_id: int,
    patch: OrderBuyPatch,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Partially update an order (status / description_order).

    Accepts JSON body, e.g.:
    {
        "status": "pending",
        "description_order": "wqw"
    }
    """

    order = await OrderBuyRepository.get_by_id(session, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if order.user_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this order")

    # Run lifecycle side-effects BEFORE mutating order.status so the service
    # can read the previous status to detect genuine transitions.
    if patch.status is not None:
        await on_status_transition(session, order, patch.status)

    updated = await OrderBuyRepository.update(
        session=session,
        order=order,
        status=patch.status,
        file_path=None,  # keep existing file_path unless changed via PUT
        description_order=patch.description_order,
    )

    product = await session.get(Product, updated.product_id)

    return {
        "id_order": updated.id_order,
        "user_id": updated.user_id,
        "product_id": updated.product_id,
        "status": updated.status,
        "file_path": updated.file_path,
        "description_order": updated.description_order,
        "product": {
            "id_product": product.id_product if product else None,
            "title": product.title if product else "",
            "description": product.description if product else "",
            "image": product.image if product else None,
        } if product else None,
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
