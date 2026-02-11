from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.models import LikedGame, Product, User
from app.util.util_auth import get_current_user

router = APIRouter(prefix="/liked-games", tags=["liked-games"])


class LikeGameCreate(BaseModel):
    product_id: int


@router.get("/{user_id}")
async def get_liked_games_by_user(user_id: int, session: AsyncSession = Depends(get_session)):
    """Return the list of products liked by the given user_id."""
    query = (
        select(LikedGame)
        .options(selectinload(LikedGame.product))
        .where(LikedGame.user_id == user_id)
    )

    result = await session.execute(query)
    liked_games = result.scalars().all()

    data = [
        {
            "liked_id": lg.id,
            "user_id": lg.user_id,
            "product": {
                "id_product": lg.product.id_product,
                "title": lg.product.title,
                "description": lg.product.description,
                "image": lg.product.image,
                "calification": lg.product.calification,
                "puntos_venta": lg.product.puntos_venta,
                "puede_rentarse": lg.product.puede_rentarse,
                "destacado": lg.product.destacado,
            } if isinstance(lg.product, Product) else None,
        }
        for lg in liked_games
    ]

    return {"data": data}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def like_game(
    payload: LikeGameCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Store a liked game for the current authenticated user."""

    # Ensure the product exists
    product = await session.get(Product, payload.product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Check if it's already liked
    query = select(LikedGame).where(
        LikedGame.user_id == current_user.id,
        LikedGame.product_id == payload.product_id,
    )
    result = await session.execute(query)
    existing = result.scalars().first()

    if existing:
        return {
            "liked_id": existing.id,
            "user_id": existing.user_id,
            "product_id": existing.product_id,
            "message": "Game already liked",
        }

    liked_game = LikedGame(user_id=current_user.id, product_id=payload.product_id)
    session.add(liked_game)
    await session.commit()
    await session.refresh(liked_game)

    return {
        "liked_id": liked_game.id,
        "user_id": liked_game.user_id,
        "product_id": liked_game.product_id,
    }


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_liked_game(
    product_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete a liked game for the current authenticated user by product_id."""

    query = select(LikedGame).where(
        LikedGame.user_id == current_user.id,
        LikedGame.product_id == product_id,
    )
    result = await session.execute(query)
    liked_game = result.scalars().first()

    if not liked_game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Liked game not found",
        )

    await session.delete(liked_game)
    await session.commit()

    # 204 No Content
    return None
