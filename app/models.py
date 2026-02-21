from sqlalchemy import Column, Integer, String, Date, ForeignKey, Boolean, Table, DateTime, modifier, null
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

products_products_consola = Table(
    "products_products_consola", Base.metadata,
    Column("products_id", Integer, ForeignKey("products_products.id_product"), primary_key=True),
    Column("consoles_id", Integer, ForeignKey("products_consoles.id_console"), primary_key=True),
)

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
    consoles = relationship("Consoles", secondary=products_products_consola, back_populates="products", lazy="selectin")


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

    # relación inversa many-to-many — debe coincidir con Product.consoles
    products = relationship(
        "Product",
        secondary=products_products_consola,
        back_populates="consoles",
        lazy="selectin",
    )

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
    
class User(Base):
    __tablename__ = "auth_user"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    password = Column(String(128), nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)
    is_superuser = Column(Boolean, nullable=False, default=False)
    username = Column(String(150), unique=True, index=True, nullable=False)
    first_name = Column(String(150), nullable=False, default="")
    last_name = Column(String(150), nullable=False, default="")
    email = Column(String(254), nullable=False, default="")
    is_staff = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    date_joined = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class UserCustomized(Base):
    __tablename__ = "user_customized_user_customized"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("auth_user.id"), unique=True, nullable=False)
    phone_number = Column(String(50), nullable=False, default="")
    avatar = Column(String(500), nullable=False, default="")
    puntos = Column(Integer, nullable=False, default=0)

    user = relationship("User", backref="custom_profile", lazy="joined")


class LikedGame(Base):
    __tablename__ = "user_liked_games"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("auth_user.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products_products.id_product"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    user = relationship("User", backref="liked_games")
    product = relationship("Product", backref="liked_by_users")


class OrderBuy(Base):
    __tablename__ = "orders_buy"

    id_order = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("auth_user.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products_gamedetail.id_game_detail"), nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    file_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    modified_at = Column(DateTime(timezone=True), nullable=True, default=None, onupdate=datetime.utcnow)

    user = relationship("User", backref="orders_buy")
    product = relationship("GameDetail", backref="orders_buy")


class ShoppingCar(Base):
    __tablename__ = "products_shoppingcar"

    id_shopping_car = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column("usuario_id", Integer, ForeignKey("auth_user.id"), nullable=False)
    product_id = Column("producto_id", Integer, ForeignKey("products_gamedetail.id_game_detail"), nullable=False)
    estado = Column(Boolean, nullable=False, default=True)

    user = relationship("User", backref="shopping_cars")
    product = relationship("GameDetail", backref="shopping_cars")


class Coupon(Base):
    __tablename__ = "coupons_coupon"

    id_coupon = Column(Integer, primary_key=True, autoincrement=True)
    name_coupon = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    modified_at = Column(DateTime(timezone=True), nullable=True, default=None, onupdate=datetime.utcnow)
    expiration_date = Column(DateTime(timezone=True), nullable=False)
    is_valid = Column(Boolean, nullable=False, default=True)
    user_id = Column(Integer, ForeignKey("auth_user.id"), nullable=True)
    percentage_off = Column(Integer, nullable=False, default=0)
    points_given = Column(Integer, nullable=False, default=0)
    product_id = Column(Integer, ForeignKey("products_products.id_product"), nullable=True)

    user = relationship("User", backref="coupons")
    product = relationship("Product", backref="coupons")