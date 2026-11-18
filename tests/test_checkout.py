"""Unit and integration test suite for checkout-ledger.

Tests cover multi-item cart calculation, tiered discount coupon stacking,
free shipping thresholds, regional VAT/tax calculation, currency conversion,
and error conditions.
"""

from decimal import Decimal
import pytest

from ledger.checkout import CartItem, CheckoutEngine, CheckoutReceipt, Coupon


# ============================================================================
# CartItem Tests
# ============================================================================

def test_cart_item_subtotal_calculation():
    """Verify line-item subtotal equals price multiplied by quantity."""
    item = CartItem(sku="SKU-101", name="Wireless Mouse", price=Decimal("29.99"), quantity=3)
    assert item.subtotal == Decimal("89.97")


def test_cart_item_default_quantity():
    """Verify default quantity is 1."""
    item = CartItem(sku="SKU-102", name="USB-C Cable", price=Decimal("12.50"))
    assert item.quantity == 1
    assert item.subtotal == Decimal("12.50")


def test_cart_item_invalid_price():
    """Verify negative price raises ValueError."""
    with pytest.raises(ValueError, match="Price cannot be negative"):
        CartItem(sku="SKU-ERR", name="Bad Item", price=Decimal("-5.00"))


def test_cart_item_invalid_quantity():
    """Verify quantity less than 1 raises ValueError."""
    with pytest.raises(ValueError, match="Quantity must be at least 1"):
        CartItem(sku="SKU-ERR", name="Bad Item", price=Decimal("10.00"), quantity=0)


# ============================================================================
# Empty Cart Edge Cases
# ============================================================================

def test_empty_cart_zero_totals():
    """Verify empty cart produces zero subtotal, tax, shipping, and grand total."""
    engine = CheckoutEngine(region="US-NY")
    receipt = engine.checkout()

    assert receipt.subtotal == Decimal("0.00")
    assert receipt.discount_total == Decimal("0.00")
    assert receipt.taxable_subtotal == Decimal("0.00")
    assert receipt.tax_amount == Decimal("0.00")
    assert receipt.shipping_fee == Decimal("0.00")
    assert receipt.total == Decimal("0.00")
    assert receipt.items_count == 0


# ============================================================================
# Multi-Item Cart Calculations
# ============================================================================

def test_multi_item_cart_subtotal():
    """Verify accurate subtotal calculation across diverse prices and quantities."""
    engine = CheckoutEngine()
    engine.add_item(CartItem(sku="SKU-A", name="Mechanical Keyboard", price=Decimal("89.99"), quantity=2))  # 179.98
    engine.add_item(CartItem(sku="SKU-B", name="Desk Mat", price=Decimal("24.50"), quantity=1))            # 24.50
    engine.add_item(CartItem(sku="SKU-C", name="Keycap Puller", price=Decimal("4.75"), quantity=4))         # 19.00

    expected_subtotal = Decimal("179.98") + Decimal("24.50") + Decimal("19.00")  # 223.48
    assert engine.calculate_subtotal() == expected_subtotal


# ============================================================================
# Coupon & Discount Stacking Tests
# ============================================================================

def test_single_coupon_fixed_discount():
    """Verify fixed-amount coupon discount."""
    engine = CheckoutEngine()
    engine.add_item(CartItem(sku="SKU-1", name="Product", price=Decimal("75.00"), quantity=1))
    coupon = Coupon(code="SAVE15", discount_type="fixed", value=Decimal("15.00"))
    engine.add_coupon(coupon)

    discount = engine.apply_coupons(engine.calculate_subtotal())
    assert discount == Decimal("15.00")


def test_single_coupon_percentage_discount():
    """Verify percentage coupon discount with proper decimal rounding."""
    engine = CheckoutEngine()
    engine.add_item(CartItem(sku="SKU-1", name="Product", price=Decimal("85.50"), quantity=1))
    coupon = Coupon(code="OFF10", discount_type="percentage", value=Decimal("0.10"))
    engine.add_coupon(coupon)

    # 85.50 * 0.10 = 8.55
    discount = engine.apply_coupons(engine.calculate_subtotal())
    assert discount == Decimal("8.55")


def test_fixed_coupon_capped_at_subtotal():
    """Verify fixed discount never exceeds total subtotal."""
    engine = CheckoutEngine()
    engine.add_item(CartItem(sku="SKU-1", name="Small Item", price=Decimal("15.00"), quantity=1))
    coupon = Coupon(code="SAVE50", discount_type="fixed", value=Decimal("50.00"))
    engine.add_coupon(coupon)

    discount = engine.apply_coupons(engine.calculate_subtotal())
    assert discount == Decimal("15.00")


def test_coupon_min_spend_threshold():
    """Verify coupon is skipped if subtotal does not meet minimum spend."""
    engine = CheckoutEngine()
    engine.add_item(CartItem(sku="SKU-1", name="Product", price=Decimal("49.99"), quantity=1))
    coupon = Coupon(code="BIGSPEND", discount_type="fixed", value=Decimal("10.00"), min_spend=Decimal("50.00"))
    engine.add_coupon(coupon)

    discount = engine.apply_coupons(engine.calculate_subtotal())
    assert discount == Decimal("0.00")


def test_tiered_coupon_stacking():
    """Verify multiple valid coupons are stacked sequentially."""
    engine = CheckoutEngine()
    engine.add_item(CartItem(sku="SKU-1", name="Product", price=Decimal("200.00"), quantity=1))

    # Tier 1: 15% off 200.00 = 30.00 discount (subtotal becomes 170.00)
    engine.add_coupon(Coupon(code="PERCENT15", discount_type="percentage", value=Decimal("0.15")))
    # Tier 2: $20 off 170.00 = 20.00 discount (subtotal becomes 150.00)
    engine.add_coupon(Coupon(code="FIXED20", discount_type="fixed", value=Decimal("20.00")))

    total_discount = engine.apply_coupons(engine.calculate_subtotal())
    assert total_discount == Decimal("50.00")


def test_coupon_stacking_with_expired_coupons():
    """Verify that expired coupons are pruned and subsequent valid coupons are applied.

    CRITICAL BUG EXPECTATION:
    When iterating over `self.coupons` while calling `self.coupons.remove()` on the expired
    coupon, Python advances the internal index past `SAVE10`, skipping it completely!
    """
    engine = CheckoutEngine()
    engine.add_item(CartItem(sku="SKU-1", name="Item", price=Decimal("100.00"), quantity=1))

    c_expired = Coupon(code="EXPIRED_DEAL", discount_type="percentage", value=Decimal("0.20"), is_expired=True)
    c_valid1 = Coupon(code="SAVE10", discount_type="percentage", value=Decimal("0.10"), is_expired=False)
    c_valid2 = Coupon(code="FLAT5", discount_type="fixed", value=Decimal("5.00"), is_expired=False)

    engine.add_coupon(c_expired)
    engine.add_coupon(c_valid1)
    engine.add_coupon(c_valid2)

    total_discount = engine.apply_coupons(Decimal("100.00"))

    # Expected: c_expired removed.
    # c_valid1 applies: 100.00 * 0.10 = 10.00 discount (running total 90.00)
    # c_valid2 applies: 5.00 discount
    # Total expected discount = 15.00
    assert total_discount == Decimal("15.00")
    # Expired coupon must be pruned, leaving only the 2 valid coupons
    assert len(engine.coupons) == 2
    assert all(not c.is_expired for c in engine.coupons)


def test_consecutive_expired_coupons_pruning():
    """Verify multiple consecutive expired coupons are all correctly pruned.

    CRITICAL BUG EXPECTATION:
    With naive iteration, removing the first expired coupon shifts the second expired
    coupon to the current index, so the loop counter skips it without removing it.
    """
    engine = CheckoutEngine()
    c_exp1 = Coupon(code="OLD1", discount_type="fixed", value=Decimal("10.00"), is_expired=True)
    c_exp2 = Coupon(code="OLD2", discount_type="fixed", value=Decimal("10.00"), is_expired=True)
    c_valid = Coupon(code="NEW", discount_type="fixed", value=Decimal("5.00"), is_expired=False)

    engine.add_coupon(c_exp1)
    engine.add_coupon(c_exp2)
    engine.add_coupon(c_valid)

    engine.apply_coupons(Decimal("50.00"))
    assert len(engine.coupons) == 1
    assert engine.coupons[0].code == "NEW"


# ============================================================================
# Free Shipping Threshold Tests
# ============================================================================

def test_shipping_fee_below_threshold():
    """Verify standard shipping fee applies when subtotal is below threshold."""
    engine = CheckoutEngine(free_shipping_threshold=Decimal("100.00"), standard_shipping_fee=Decimal("10.00"))
    engine.add_item(CartItem(sku="SKU-1", name="Product", price=Decimal("99.99"), quantity=1))

    assert engine.calculate_shipping(Decimal("99.99")) == Decimal("10.00")


def test_shipping_fee_at_or_above_threshold():
    """Verify free shipping applies when taxable subtotal meets or exceeds threshold."""
    engine = CheckoutEngine(free_shipping_threshold=Decimal("100.00"), standard_shipping_fee=Decimal("10.00"))
    engine.add_item(CartItem(sku="SKU-1", name="Product", price=Decimal("100.00"), quantity=1))

    # Exactly at threshold
    assert engine.calculate_shipping(Decimal("100.00")) == Decimal("0.00")
    # Above threshold
    assert engine.calculate_shipping(Decimal("150.00")) == Decimal("0.00")


# ============================================================================
# Regional Tax Calculation Tests (Triggers Decimal vs Float Bug)
# ============================================================================

def test_tax_calculation_new_york():
    """Verify 8% tax calculation for US-NY on discounted taxable subtotal.

    CRITICAL BUG EXPECTATION:
    Raises `TypeError: unsupported operand type(s) for *: 'Decimal' and 'float'`
    because US-NY tax rate is passed as float 0.08 while subtotal is Decimal.
    """
    engine = CheckoutEngine(region="US-NY")
    taxable_subtotal = Decimal("100.00")
    # 100.00 * 0.08 = 8.00
    tax = engine.calculate_tax(taxable_subtotal, region="US-NY")
    assert tax == Decimal("8.00")


def test_tax_calculation_california():
    """Verify 7.25% tax calculation for US-CA."""
    engine = CheckoutEngine(region="US-CA")
    taxable_subtotal = Decimal("200.00")
    # 200.00 * 0.0725 = 14.50
    tax = engine.calculate_tax(taxable_subtotal, region="US-CA")
    assert tax == Decimal("14.50")


def test_tax_calculation_germany_vat():
    """Verify 19% VAT calculation for EU-DE."""
    engine = CheckoutEngine(region="EU-DE")
    taxable_subtotal = Decimal("150.00")
    # 150.00 * 0.19 = 28.50
    tax = engine.calculate_tax(taxable_subtotal, region="EU-DE")
    assert tax == Decimal("28.50")


def test_tax_calculation_uk_vat():
    """Verify 20% VAT calculation for UK."""
    engine = CheckoutEngine(region="UK")
    taxable_subtotal = Decimal("75.50")
    # 75.50 * 0.20 = 15.10
    tax = engine.calculate_tax(taxable_subtotal, region="UK")
    assert tax == Decimal("15.10")


def test_tax_calculation_zero_tax_region():
    """Verify zero-tax region returns 0.00 tax."""
    engine = CheckoutEngine(region="ZERO")
    taxable_subtotal = Decimal("100.00")
    tax = engine.calculate_tax(taxable_subtotal, region="ZERO")
    assert tax == Decimal("0.00")


# ============================================================================
# Currency Conversion Tests
# ============================================================================

def test_currency_conversion_supported():
    """Verify currency conversions from USD base to EUR, GBP, CAD, and JPY."""
    engine = CheckoutEngine(currency="USD")
    base_amount = Decimal("100.00")

    # Rates: EUR: 0.92, GBP: 0.78, CAD: 1.35, JPY: 155.00
    assert engine.convert_currency(base_amount, "EUR") == Decimal("92.00")
    assert engine.convert_currency(base_amount, "GBP") == Decimal("78.00")
    assert engine.convert_currency(base_amount, "CAD") == Decimal("135.00")
    assert engine.convert_currency(base_amount, "JPY") == Decimal("15500.00")
    assert engine.convert_currency(base_amount, "USD") == Decimal("100.00")


def test_currency_conversion_unknown_currency():
    """Verify unsupported currency raises ValueError."""
    engine = CheckoutEngine(currency="USD")
    with pytest.raises(ValueError, match="Exchange rate for currency 'XYZ' not configured"):
        engine.convert_currency(Decimal("50.00"), "XYZ")


# ============================================================================
# End-to-End Checkout Pipeline Test
# ============================================================================

def test_end_to_end_checkout_with_discounts_tax_and_shipping():
    """Comprehensive end-to-end checkout test asserting exact ledger totals.

    Pipeline:
    1. Cart:
       - 2x Mechanical Keyboard @ 79.99 = 159.98
       - 1x Keycap Set @ 25.50 = 25.50
       - Subtotal = 185.48
    2. Coupons:
       - EXPIRED50 (expired, 50% off) -> skipped & removed
       - SPRING10 (valid, 10% off) -> 185.48 * 0.10 = 18.55 (rounded half up), remainder = 166.93
       - VIP15 (valid, $15.00 fixed) -> min(15.00, 166.93) = 15.00
       - Total discount = 18.55 + 15.00 = 33.55
       - Taxable subtotal = 185.48 - 33.55 = 151.93
    3. Shipping:
       - Taxable subtotal 151.93 >= 100.00 free shipping threshold -> 0.00
    4. Regional Tax:
       - Region US-NY (8% rate): 151.93 * 0.08 = 12.1544 -> 12.15
    5. Grand Total:
       - 151.93 (taxable subtotal) + 12.15 (tax) + 0.00 (shipping) = 164.08
    """
    engine = CheckoutEngine(region="US-NY", currency="USD")
    engine.add_item(CartItem(sku="KB-01", name="Mechanical Keyboard", price=Decimal("79.99"), quantity=2))
    engine.add_item(CartItem(sku="KC-02", name="Keycap Set", price=Decimal("25.50"), quantity=1))

    engine.add_coupon(Coupon(code="EXPIRED50", discount_type="percentage", value=Decimal("0.50"), is_expired=True))
    engine.add_coupon(Coupon(code="SPRING10", discount_type="percentage", value=Decimal("0.10"), is_expired=False))
    engine.add_coupon(Coupon(code="VIP15", discount_type="fixed", value=Decimal("15.00"), is_expired=False))

    receipt: CheckoutReceipt = engine.checkout()

    assert receipt.subtotal == Decimal("185.48")
    assert receipt.discount_total == Decimal("33.55")
    assert receipt.taxable_subtotal == Decimal("151.93")
    assert receipt.tax_amount == Decimal("12.15")
    assert receipt.shipping_fee == Decimal("0.00")
    assert receipt.total == Decimal("164.08")
    assert receipt.currency == "USD"
    assert receipt.region == "US-NY"
    assert receipt.items_count == 3
