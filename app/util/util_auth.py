from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from itsdangerous import URLSafeTimedSerializer
import os

from app.database import get_session
from app.models import User

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here-CHANGE-IN-PRODUCTION")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
RESET_SECRET_KEY = os.getenv("RESET_SECRET_KEY", SECRET_KEY)
RESET_TOKEN_EXPIRE_SECONDS = int(os.getenv("RESET_TOKEN_EXPIRE_SECONDS", "3600"))


pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "django_pbkdf2_sha256", "bcrypt"],
    deprecated="auto"
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

reset_serializer = URLSafeTimedSerializer(RESET_SECRET_KEY)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica que una contraseña en texto plano coincida con su hash.
    Soporta múltiples formatos de hash (Django PBKDF2, bcrypt, etc.)
    
    Args:
        plain_password: Contraseña ingresada por el usuario
        hashed_password: Hash almacenado en BD
    
    Returns:
        True si coinciden, False en caso contrario
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Genera hash de contraseña usando el formato de Django (PBKDF2-SHA256).
    Mantiene compatibilidad con tabla auth_user existente.
    
    Args:
        password: Contraseña en texto plano
    
    Returns:
        Hash en formato Django: pbkdf2_sha256$iterations$salt$hash
    """
    return pwd_context.hash(password, scheme="pbkdf2_sha256")

# ==============================================================================
# FUNCIONES DE JWT (ACCESS TOKENS)
# ==============================================================================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """
    Crea un token JWT firmado para autenticación de sesión.
    
    Args:
        data: Datos a incluir en el token (ej: {"sub": username})
        expires_delta: Tiempo de expiración personalizado (default: 15 min)
    
    Returns:
        Token JWT firmado como string
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    session: AsyncSession = Depends(get_session)
):
    """
    Dependencia para endpoints protegidos.
    Valida el token JWT y retorna el usuario autenticado.
    
    Args:
        token: Token JWT del header Authorization
        session: Sesión de BD (inyectada por FastAPI)
    
    Returns:
        Usuario autenticado
    
    Raises:
        HTTPException 401 si token inválido o usuario no encontrado
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    from sqlalchemy import select
    result = await session.execute(select(User).filter(User.username == username))
    user = result.scalars().first()
    if user is None:
        raise credentials_exception
    return user

# ==============================================================================
# FUNCIONES DE RESET DE CONTRASEÑA (STATELESS)
# ==============================================================================

def generate_reset_token(email: str) -> str:
    """
    Genera token firmado para reset de contraseña.
    El token contiene el email del usuario y expira automáticamente.
    No requiere almacenamiento en base de datos (stateless).
    
    Args:
        email: Email del usuario que solicita el reset
    
    Returns:
        Token firmado URL-safe (puede usarse en query params)
    
    Ejemplo:
        token = generate_reset_token("user@example.com")
        # Resultado: "ImFkbWluQGV4YW1wbGUuY29tIg.Z..."
    """
    return reset_serializer.dumps(email, salt='password-reset-salt')


def verify_reset_token(token: str, max_age: int = RESET_TOKEN_EXPIRE_SECONDS) -> str | None:
    """
    Verifica token de reset y extrae el email del usuario.
    Valida firma criptográfica y expiración automáticamente.
    
    Args:
        token: Token recibido del usuario (generado por generate_reset_token)
        max_age: Tiempo de validez en segundos (default: 3600 = 1 hora)
    
    Returns:
        Email del usuario si el token es válido
        None si el token es inválido, expirado o ha sido manipulado
    
    Ejemplo:
        email = verify_reset_token(token_from_url)
        if email:
            # Token válido, proceder con reset
        else:
            # Token inválido o expirado
    """
    try:
        email = reset_serializer.loads(
            token, 
            salt='password-reset-salt', 
            max_age=max_age
        )
        return email
    except Exception:
        # Captura todas las excepciones de itsdangerous:
        # - SignatureExpired: Token expiró
        # - BadSignature: Token manipulado o clave incorrecta
        # - BadData: Datos corruptos
        return None