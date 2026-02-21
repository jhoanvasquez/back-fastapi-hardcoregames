from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import User, UserCustomized
from app.util.util_auth import get_password_hash

async def get_user_by_username(session: AsyncSession, username: str):
    result = await session.execute(select(User).filter(User.username == username))
    return result.scalars().first()

async def get_user_by_email(session: AsyncSession, email: str):
    result = await session.execute(select(User).filter(User.email == email))
    return result.scalars().first()

async def create_user(
    session: AsyncSession,
    username: str,
    email: str,
    password: str,
    phone_number: str = "",
    avatar: str = "",
):
    """Create base auth user plus associated UserCustomized profile."""

    hashed_password = get_password_hash(password)
    db_user = User(username=username, email=email, password=hashed_password)
    session.add(db_user)

    # flush to assign primary key without committing yet
    await session.flush()

    profile = UserCustomized(
        user_id=db_user.id,
        phone_number=phone_number or "",
        avatar=avatar or "",
        puntos=0,
    )
    session.add(profile)

    await session.commit()
    await session.refresh(db_user)
    return db_user


async def update_user_password(session: AsyncSession, user: User, new_password: str) -> User:
    hashed_password = get_password_hash(new_password)
    user.password = hashed_password
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
