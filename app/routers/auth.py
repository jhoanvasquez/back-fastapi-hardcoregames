from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr, constr, json
from sqlalchemy.orm import selectinload
from sqlalchemy import select 
from app.database import get_session
from app.models import LikedGame, Product, User, UserCustomized
from app.util.util_auth import (
    verify_password,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    generate_reset_token,
    verify_reset_token,
    RESET_TOKEN_EXPIRE_SECONDS,
    get_current_user,
)
from app.repositories import auth as auth_repo

router = APIRouter(prefix="/auth", tags=["authentication"])

class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str
    phone_number: str | None = ""
    avatar: str | None = ""


class UserProfileUpdate(BaseModel):
    """Full user profile payload used for PUT.

    All fields are required and represent the complete resource
    state that should be stored for the user.
    """

    first_name: str
    last_name: str
    phone_number: str
    email: EmailStr


class UserProfilePatch(BaseModel):
    """Partial user profile payload used for PATCH.

    Only fields that are present and non-empty will be updated.
    """

    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    email: EmailStr | None = None

class LikedProduct(BaseModel):
    id_product: int
    title: str
    image: str | None = None

class Token(BaseModel):
    access_token: str
    token_type: str
    is_superuser: bool
    # liked_games: list[LikedProduct]


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: constr(min_length=8)
    confirm_password: constr(min_length=8)

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(user: UserRegister, session: AsyncSession = Depends(get_session)):
    db_user = await auth_repo.get_user_by_username(session, username=user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    db_user = await auth_repo.get_user_by_email(session, email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    await auth_repo.create_user(
        session,
        username=user.username,
        email=user.email,
        password=user.password,
        phone_number=user.phone_number or "",
        avatar=user.avatar or "",
    )
    return {"message": "User created successfully"}

@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
):
    user = await auth_repo.get_user_by_username(session, username=form_data.username)
    if not user or not verify_password(form_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    query = (
        select(LikedGame)
        .options(selectinload(LikedGame.product))
        .where(LikedGame.user_id == user.id)
    )
    result = await session.execute(query)
    liked_games = result.scalars().all()

    liked_data = [
        LikedProduct(
            id_product=lg.product.id_product,
            title=lg.product.title,
            image=lg.product.image,
        )
        for lg in liked_games
        if isinstance(lg.product, Product)
    ]

    access_token = create_access_token(
        data={
            "sub": user.username, 
            "user_id": user.id, 
            "liked_game_ids": [lg.id_product for lg in liked_data],
            "is_superuser": bool(getattr(user, "is_superuser", False)),
            }, 
        expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "is_superuser": bool(getattr(user, "is_superuser", False)),
    }


@router.post("/refresh", response_model=Token)
async def refresh_token(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Issue a new access token for the currently authenticated user."""

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    query = (
        select(LikedGame)
        .options(selectinload(LikedGame.product))
        .where(LikedGame.user_id == current_user.id)
    )
    result = await session.execute(query)
    liked_games = result.scalars().all()

    liked_ids = [
        lg.product.id_product
        for lg in liked_games
        if isinstance(lg.product, Product)
    ]

    access_token = create_access_token(
        data={
            "sub": current_user.username,
            "user_id": current_user.id,
            "liked_game_ids": liked_ids,
            "is_superuser": bool(getattr(current_user, "is_superuser", False)),
        },
        expires_delta=access_token_expires,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "is_superuser": bool(getattr(current_user, "is_superuser", False)),
    }

@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, session: AsyncSession = Depends(get_session)):
    user = await auth_repo.get_user_by_email(session, email=payload.email)
    if not user:
        # Respuesta uniforme para evitar filtrar la existencia del usuario
        return {
            "message": "Si el correo existe recibirás un enlace de recuperación.",
            "reset_token": None,
            "expires_in": RESET_TOKEN_EXPIRE_SECONDS,
        }

    reset_token = generate_reset_token(user.email)
    # TODO: enviar reset_token por correo electrónico
    return {
        "message": "Token de recuperación generado. Revisa tu correo.",
        "reset_token": reset_token,
        "expires_in": RESET_TOKEN_EXPIRE_SECONDS,
    }


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest, session: AsyncSession = Depends(get_session)):
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Las contraseñas no coinciden")

    email = verify_reset_token(payload.token)
    if not email:
        raise HTTPException(status_code=400, detail="Token inválido o expirado")

    user = await auth_repo.get_user_by_email(session, email=email)
    if not user:
        raise HTTPException(status_code=400, detail="El usuario ya no existe")

    await auth_repo.update_user_password(session, user=user, new_password=payload.new_password)
    return {"message": "Contraseña actualizada correctamente"}


@router.put("/update-profile")
async def update_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
        """Full update of the authenticated user's basic profile.

        Expects the complete resource (first_name, last_name, phone_number, email)
        and replaces existing values with the provided ones.
        """

        user = await session.get(User, current_user.id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Ensure new email (if changed) is not already in use by another user
        if payload.email != user.email:
            existing = await auth_repo.get_user_by_email(session, email=payload.email)
            if existing and existing.id != user.id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

        # Replace core fields
        user.first_name = payload.first_name
        user.last_name = payload.last_name
        user.email = payload.email

        # Upsert customized profile for phone_number (always set on full update)
        result = await session.execute(
            select(UserCustomized).where(UserCustomized.user_id == user.id)
        )
        profile = result.scalars().first()
        if profile is None:
            profile = UserCustomized(
                user_id=user.id,
                phone_number=payload.phone_number or "",
                avatar="",
                puntos=0,
            )
            session.add(profile)
        else:
            profile.phone_number = payload.phone_number or ""

        session.add(user)
        await session.commit()
        await session.refresh(user)

        # Re-read profile for response
        result = await session.execute(
            select(UserCustomized).where(UserCustomized.user_id == user.id)
        )
        profile = result.scalars().first()

        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone_number": getattr(profile, "phone_number", ""),
        }
    
    
@router.patch("/update-profile")
async def patch_profile(
    payload: UserProfilePatch,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Partial update of the authenticated user's basic profile.

    Only fields that are present in the payload and non-empty are updated.
    """

    user = await session.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Only update names if provided and not empty string
    if payload.first_name is not None and payload.first_name != "":
        user.first_name = payload.first_name
    if payload.last_name is not None and payload.last_name != "":
        user.last_name = payload.last_name

    # Upsert customized profile for phone_number
    if payload.phone_number is not None and payload.phone_number != "":
        result = await session.execute(
            select(UserCustomized).where(UserCustomized.user_id == user.id)
        )
        profile = result.scalars().first()
        if profile is None:
            profile = UserCustomized(
                user_id=user.id,
                phone_number=payload.phone_number or "",
                avatar="",
                puntos=0,
            )
            session.add(profile)
        else:
            profile.phone_number = payload.phone_number or ""
    else:
        # Still need profile object for response even if not modified
        result = await session.execute(
            select(UserCustomized).where(UserCustomized.user_id == user.id)
        )
        profile = result.scalars().first()

    # Optionally update email if provided and non-empty
    if payload.email is not None and payload.email != "" and payload.email != user.email:
        existing = await auth_repo.get_user_by_email(session, email=payload.email)
        if existing and existing.id != user.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
        user.email = payload.email

    session.add(user)
    await session.commit()
    await session.refresh(user)

    # Re-read profile (in case it was created above)
    result = await session.execute(
        select(UserCustomized).where(UserCustomized.user_id == user.id)
    )
    profile = result.scalars().first()

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone_number": getattr(profile, "phone_number", ""),
    }