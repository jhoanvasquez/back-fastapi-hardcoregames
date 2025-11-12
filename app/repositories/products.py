from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from ..models import Product

class ProductRepository:

    @staticmethod
    async def get_all(session: AsyncSession):
        result = await session.execute(select(Product))
        return result.scalars().all()

    @staticmethod
    async def create(session: AsyncSession, title: str, description: str):
        product = Product(title=title, description=description)
        session.add(product)
        await session.commit()
        await session.refresh(product)
        return product
