from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import OrderBuy


class OrderBuyRepository:

    @staticmethod
    async def get_all(session: AsyncSession):
        result = await session.execute(select(OrderBuy))
        return result.scalars().all()

    @staticmethod
    async def get_by_id(session: AsyncSession, order_id: int) -> OrderBuy | None:
        return await session.get(OrderBuy, order_id)

    @staticmethod
    async def create_no_commit(
        session: AsyncSession,
        user_id: int,
        product_id: int,
        status: str = "pending",
        file_path: str | None = None,
        id_license: int | None = None,
        id_console: int | None = None,
    ) -> OrderBuy:
        """Add a new OrderBuy to the session and flush to obtain its PK.

        Does NOT commit.  The caller is responsible for committing (or rolling
        back) the surrounding transaction.  This allows order creation and
        stock decrement to be committed atomically in a single transaction.
        """
        order = OrderBuy(
            user_id=user_id,
            product_id=product_id,
            status=status,
            file_path=file_path,
            id_license=id_license,
            id_console=id_console,
        )
        session.add(order)
        await session.flush()  # populate order.id_order without committing
        return order

    @staticmethod
    async def create(
        session: AsyncSession,
        user_id: int,
        product_id: int,
        status: str = "pending",
        file_path: str | None = None,
    ) -> OrderBuy:
        order = OrderBuy(
            user_id=user_id,
            product_id=product_id,
            status=status,
            file_path=file_path,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order

    @staticmethod
    async def update(
        session: AsyncSession,
        order: OrderBuy,
        *,
        status: str | None = None,
        file_path: str | None = None,
        description_order: str | None = None,
    ) -> OrderBuy:
        if status is not None:
            order.status = status
        if file_path is not None:
            order.file_path = file_path
        if description_order is not None:
            order.description_order = description_order
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order

    @staticmethod
    async def delete(session: AsyncSession, order: OrderBuy) -> None:
        await session.delete(order)
        await session.commit()
