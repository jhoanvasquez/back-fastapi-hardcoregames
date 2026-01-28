from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr, constr
from app.database import get_session
from app.util.util_auth import (
    verify_password,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    generate_reset_token,
    verify_reset_token,
    RESET_TOKEN_EXPIRE_SECONDS,
)
from app.repositories import auth as auth_repo

router = APIRouter(prefix="/auth", tags=["authentication"])

class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str


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
    
    await auth_repo.create_user(session, username=user.username, email=user.email, password=user.password)
    return {"message": "User created successfully"}

@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), session: AsyncSession = Depends(get_session)):
    user = await auth_repo.get_user_by_username(session, username=form_data.username)
    if not user or not verify_password(form_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


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