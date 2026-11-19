"""Production checkout and billing ledger engine.
Test-1
Provides core billing capabilities including multi-item cart management,
tiered discount coupon stacking, regional VAT/tax calculation, and currency conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional


@dataclass
class CartItem:
    """Represents a product item in the shopping cart.

    Attributes:
        sku: Stock Keeping Unit identifier.
        name: Human-readable product name.
        price: Unit price in base currency (Decimal).
        quantity: Number of units purchased (default 1).
    """

    sku: str
    name: str
    price: Decimal
    quantity: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.price, Decimal):
            self.price = Decimal(str(self.price))
        if self.price < Decimal("0.00"):
            raise ValueError(f"Price cannot be negative for SKU '{self.sku}'")
        if self.quantity < 1:
            raise ValueError(f"Quantity must be at least 1 for SKU '{self.sku}'")

    @property
    def subtotal(self) -> Decimal:
        """Calculate line item subtotal price (price * quantity)."""
        return (self.price * self.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Coupon:
    """Represents a discount coupon applicable to the cart.

    Attributes:
        code: Unique promotional coupon code.
        discount_type: Type of discount ('percentage' or 'fixed').
        value: Discount magnitude (e.g., Decimal('0.10') for 10% or Decimal('15.00') for $15).
        min_spend: Minimum cart subtotal required to qualify for this discount.
        is_expired: Flag indicating whether coupon validity has expired.
    """

    code: str
    discount_type: str
    value: Decimal
    min_spend: Decimal = Decimal("0.00")
    is_expired: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            self.value = Decimal(str(self.value))
        if not isinstance(self.min_spend, Decimal):
            self.min_spend = Decimal(str(self.min_spend))
        if self.discount_type not in ("percentage", "fixed"):
            raise ValueError(f"Invalid discount_type: '{self.discount_type}'. Must be 'percentage' or 'fixed'.")
        if self.value < Decimal("0.00"):
            raise ValueError(f"Coupon value cannot be negative for coupon '{self.code}'")
        if self.discount_type == "percentage" and self.value > Decimal("1.00"):
            raise ValueError(f"Percentage discount cannot exceed 1.0 (100%) for coupon '{self.code}'")


@dataclass(frozen=True)
class CheckoutReceipt:
    """Immutable final billing ledger summary returned upon checkout."""

    subtotal: Decimal
    discount_total: Decimal
    taxable_subtotal: Decimal
    tax_rate: float
    tax_amount: Decimal
    shipping_fee: Decimal
    total: Decimal
    currency: str
    region: str
    items_count: int


class CheckoutEngine:
    """Core billing and checkout ledger engine.

    Handles multi-item cart accumulation, tiered coupon stack evaluation,
    regional VAT/sales tax application, shipping thresholds, and multi-currency conversion.
    """

    DEFAULT_TAX_RATES: Dict[str, float] = {
        "US-NY": 0.08,
        "US-CA": 0.0725,
        "US-TX": 0.0625,
        "EU-DE": 0.19,
        "UK": 0.20,
        "ZERO": 0.0,
    }

    DEFAULT_EXCHANGE_RATES: Dict[str, Decimal] = {
        "USD": Decimal("1.00"),
        "EUR": Decimal("0.92"),
        "GBP": Decimal("0.78"),
        "CAD": Decimal("1.35"),
        "JPY": Decimal("155.00"),
    }

    def __init__(
        self,
        region: str = "US-NY",
        currency: str = "USD",
        free_shipping_threshold: Decimal = Decimal("100.00"),
        standard_shipping_fee: Decimal = Decimal("10.00"),
        tax_rates: Optional[Dict[str, float]] = None,
        exchange_rates: Optional[Dict[str, Decimal]] = None,
    ) -> None:
        self.region = region
        self.currency = currency
        self.free_shipping_threshold = Decimal(str(free_shipping_threshold))
        self.standard_shipping_fee = Decimal(str(standard_shipping_fee))
        self.tax_rates = dict(tax_rates) if tax_rates is not None else dict(self.DEFAULT_TAX_RATES)
        self.exchange_rates = dict(exchange_rates) if exchange_rates is not None else dict(self.DEFAULT_EXCHANGE_RATES)
        self.items: List[CartItem] = []
        self.coupons: List[Coupon] = []

    def add_item(self, item: CartItem) -> None:
        """Add a line item to the cart."""
        self.items.append(item)

    def add_coupon(self, coupon: Coupon) -> None:
        """Register a coupon for evaluation during checkout."""
        self.coupons.append(coupon)

    def calculate_subtotal(self) -> Decimal:
        """Calculate total un-discounted sum of all items in the cart."""
        if not self.items:
            return Decimal("0.00")
        total = sum((item.subtotal for item in self.items), Decimal("0.00"))
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def apply_coupons(self, subtotal: Decimal) -> Decimal:
        """Validate and apply stacked discount coupons to the subtotal.

        Applies coupons in registration order. Percentage discounts are applied
        to the running subtotal, and fixed discounts reduce the remainder down to 0.
        Expired coupons are pruned from the active coupon list.
        """
        total_discount = Decimal("0.00")
        current_subtotal = subtotal

        # CRITICAL BUG: Iteration Mutation
        # Iterating directly over `self.coupons` while calling `self.coupons.remove(coupon)`
        # mutates the underlying list in-place during traversal, causing Python's internal
        # iterator index to advance past adjacent coupons, skipping valid discounts.
        for coupon in self.coupons:
            if coupon.is_expired:
                self.coupons.remove(coupon)
                continue

            if current_subtotal < coupon.min_spend:
                continue

            if coupon.discount_type == "percentage":
                discount = (current_subtotal * coupon.value).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            elif coupon.discount_type == "fixed":
                discount = min(coupon.value, current_subtotal)
            else:
                raise ValueError(f"Unknown discount type: '{coupon.discount_type}'")

            total_discount += discount
            current_subtotal -= discount

        return total_discount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def calculate_shipping(self, taxable_subtotal: Decimal) -> Decimal:
        """Calculate shipping fee based on taxable subtotal and free shipping threshold."""
        if not self.items or taxable_subtotal == Decimal("0.00"):
            return Decimal("0.00")
        if taxable_subtotal >= self.free_shipping_threshold:
            return Decimal("0.00")
        return self.standard_shipping_fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def calculate_tax(self, taxable_subtotal: Decimal, region: Optional[str] = None) -> Decimal:
        """Calculate regional sales tax or VAT on the taxable subtotal."""
        if taxable_subtotal <= Decimal("0.00"):
            return Decimal("0.00")

        target_region = region or self.region
        if target_region not in self.tax_rates:
            raise ValueError(f"Tax rate for region '{target_region}' not configured")

        tax_rate = self.tax_rates[target_region]

        # CRITICAL BUG: Type Coercion Error
        # `tax_rate` is stored as float (e.g. 0.08) while `taxable_subtotal` is Decimal.
        # Multiplying Decimal and float raises:
        # TypeError: unsupported operand type(s) for *: 'Decimal' and 'float'
        tax_amount = taxable_subtotal * tax_rate
        return tax_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def convert_currency(self, amount: Decimal, target_currency: str) -> Decimal:
        """Convert a monetary amount from base currency to target currency."""
        if target_currency == self.currency:
            return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if target_currency not in self.exchange_rates:
            raise ValueError(f"Exchange rate for currency '{target_currency}' not configured")

        rate = self.exchange_rates[target_currency]
        return (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def checkout(self) -> CheckoutReceipt:
        """Perform end-to-end checkout and compile the final billing receipt."""
        subtotal = self.calculate_subtotal()
        if not self.items:
            tax_rate = self.tax_rates.get(self.region, 0.0)
            return CheckoutReceipt(
                subtotal=Decimal("0.00"),
                discount_total=Decimal("0.00"),
                taxable_subtotal=Decimal("0.00"),
                tax_rate=tax_rate,
                tax_amount=Decimal("0.00"),
                shipping_fee=Decimal("0.00"),
                total=Decimal("0.00"),
                currency=self.currency,
                region=self.region,
                items_count=0,
            )

        discount_total = self.apply_coupons(subtotal)
        taxable_subtotal = max(Decimal("0.00"), subtotal - discount_total)
        tax_amount = self.calculate_tax(taxable_subtotal, self.region)
        shipping_fee = self.calculate_shipping(taxable_subtotal)
        total = (taxable_subtotal + tax_amount + shipping_fee).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        tax_rate = self.tax_rates.get(self.region, 0.0)

        return CheckoutReceipt(
            subtotal=subtotal,
            discount_total=discount_total,
            taxable_subtotal=taxable_subtotal,
            tax_rate=tax_rate,
            tax_amount=tax_amount,
            shipping_fee=shipping_fee,
            total=total,
            currency=self.currency,
            region=self.region,
            items_count=sum(item.quantity for item in self.items),
        )
