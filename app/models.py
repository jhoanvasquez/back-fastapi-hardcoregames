from sqlalchemy import Column, Integer, String, Date, ForeignKey, Boolean, Table
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class Product(Base):
    __tablename__ = "products_products"
    id_product = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(100), default="")
    description = Column(String, default="")
    date_register = Column(Date, default=datetime.now)
    date_last_modified = Column(Date, default=datetime.now)
    image = Column(String(500), default="")
    calification = Column(Integer, default=0)
    puntos_venta = Column(Integer, default=0)
    puede_rentarse = Column(Boolean, default=True)
    destacado = Column(Boolean, default=False)
