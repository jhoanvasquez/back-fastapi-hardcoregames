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
    type_id_id = Column(String(50), default="")
    tipo_juego_id = Column(String(50), default="")


class GameDetail(Base):
    __tablename__ = "products_gamedetail"

    id_game_detail = Column(Integer, primary_key=True, autoincrement=True)
    producto_id = Column(Integer, ForeignKey("products_products.id_product"), nullable=True)
    consola_id = Column(Integer, ForeignKey("products_consoles.id_console"), nullable=True)       # ajustar tabla/columna
    licencia_id = Column(Integer, ForeignKey("products_licenses.id_license"), nullable=True)      # ajustar tabla/columna
    cuenta_id = Column(Integer, ForeignKey("products_productaccounts.id_product_accounts"), nullable=True)         # ajustar tabla/columna

    duracion_dias_alquiler = Column(Integer, nullable=True)
    stock = Column(Integer, default=0)
    precio = Column(Integer, default=0)
    precio_descuento = Column(Integer, default=0)

    # relaciones — ajusta los nombres de las clases si difieren en tu proyecto
    producto = relationship("Product", backref="game_details")
    consola = relationship("Consoles", backref="game_details")
    licencia = relationship("Licenses", backref="game_details")
    cuenta = relationship("ProductAccounts", backref="game_details")

    def __str__(self) -> str:
        return f"{self.consola} {self.licencia}"


class TypeAccounts(Base):
    __tablename__ = "products_typeaccounts"

    id_type_accounts = Column(Integer, primary_key=True, autoincrement=True)
    descripcion = Column(String(100), default="")

    def __str__(self) -> str:
        return getattr(self, "descripcion", "")


class Consoles(Base):
    __tablename__ = "products_consoles"

    id_console = Column(Integer, primary_key=True, autoincrement=True)
    descripcion = Column(String(100))
    estado = Column(Boolean, nullable=True)

    def __str__(self) -> str:
        return self.descripcion

    def get_id_console(self) -> int:
        return self.id_console


class Licenses(Base):
    __tablename__ = "products_licenses"

    id_license = Column(Integer, primary_key=True, autoincrement=True)
    descripcion = Column(String(100))

    def __str__(self) -> str:
        return self.descripcion

    def get_id_licence(self) -> int:
        return self.id_license


class ProductAccounts(Base):
    __tablename__ = "products_productaccounts"

    id_product_accounts = Column(Integer, primary_key=True, autoincrement=True)
    cuenta = Column(String(200))
    password = Column(String(100), nullable=True)
    activa = Column(Boolean, default=False)
    tipo_cuenta_id = Column(Integer, ForeignKey("products_typeaccounts.id_type_accounts"), nullable=True, default=1)
    dias_duracion = Column(Integer, default=0, nullable=True)
    codigo_seguridad = Column(String(500), nullable=True)

    tipo_cuenta = relationship("TypeAccounts", backref="product_accounts")

    def __str__(self) -> str:
        return self.cuenta