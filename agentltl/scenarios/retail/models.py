from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Literal


PaymentKind = Literal["credit_card", "gift_card", "paypal"]
OrderStatus = Literal[
    "pending",
    "processed",
    "delivered",
    "cancelled",
    "exchange requested",
]


@dataclass
class Address:
    address1: str
    address2: str
    city: str
    state: str
    country: str
    zip: str


@dataclass
class PaymentMethod:
    payment_method_id: str
    kind: PaymentKind
    balance: float | None = None


@dataclass
class User:
    user_id: str
    first_name: str
    last_name: str
    email: str
    address: Address
    payment_methods: dict[str, PaymentMethod]
    order_ids: list[str] = field(default_factory=list)


@dataclass
class Variant:
    item_id: str
    product_id: str
    options: dict[str, str]
    available: bool
    price: float


@dataclass
class Product:
    product_id: str
    name: str
    variants: dict[str, Variant]


@dataclass
class OrderItem:
    item_id: str
    product_id: str
    name: str
    options: dict[str, str]
    price: float


@dataclass
class PaymentRecord:
    transaction_type: Literal["payment", "refund"]
    amount: float
    payment_method_id: str


@dataclass
class Order:
    order_id: str
    user_id: str
    status: OrderStatus
    items: list[OrderItem]
    payment_history: list[PaymentRecord]
    cancel_reason: str | None = None
    exchange_items: list[str] | None = None
    exchange_new_items: list[str] | None = None
    exchange_payment_method_id: str | None = None
    exchange_price_difference: float | None = None


@dataclass
class RetailDB:
    users: dict[str, User]
    products: dict[str, Product]
    orders: dict[str, Order]

    def clone(self) -> RetailDB:
        return copy.deepcopy(self)

    def item(self, item_id: str) -> Variant | None:
        for product in self.products.values():
            variant = product.variants.get(item_id)
            if variant is not None:
                return variant
        return None

    def as_dict(self) -> dict:
        return asdict(self)
