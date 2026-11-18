# checkout-ledger

Production-style e-commerce billing & checkout ledger built with Python 3.11, `pytest`, and GitHub Actions CI.

## Overview & Architecture

`checkout-ledger` models a deterministic e-commerce checkout ledger engine designed for high-precision financial operations:
- **Multi-Item Carts**: Line items with price precision, stock keeping units (SKU), and quantity validations using `decimal.Decimal`.
- **Tiered Discount Coupons**: Sequential coupon stacking with support for percentage-based and fixed-amount discounts, minimum spend thresholds, and expired coupon lifecycle pruning.
- **Regional VAT / Sales Tax**: Jurisdiction-based tax rate application (e.g., US state sales tax, EU VAT, UK VAT) applied against the discounted taxable subtotal.
- **Dynamic Shipping Threshold**: Automated waiver of shipping fees when cart taxable subtotal qualifies for free shipping thresholds.
- **Multi-Currency Conversion**: High-precision conversion between base store currency and target checkout currencies (EUR, GBP, CAD, JPY).

---

## File Structure

```text
checkout-ledger/
├── .github/
│   └── workflows/
│       └── ci.yml             # GitHub Actions workflow running pytest on Python 3.11
├── ledger/
│   ├── __init__.py            # Package entrypoint exposing CartItem, Coupon, CheckoutEngine
│   └── checkout.py            # Core engine implementation
├── tests/
│   ├── __init__.py            # Test package marker
│   └── test_checkout.py       # Comprehensive pytest suite covering edge cases and arithmetic
├── .gitignore                 # Standard Python gitignore rules
├── pyproject.toml             # Project metadata and pytest configuration
├── requirements.txt           # Minimal runtime dependencies (pytest)
└── README.md                  # Project documentation
```

---

## Quickstart & Local Setup

### Prerequisites
- Python 3.11+
- Git

### Installation

1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows (PowerShell):
   .venv\Scripts\Activate.ps1
   # Linux / macOS:
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the test suite:
   ```bash
   pytest -v
   ```

---

## Continuous Integration (GitHub Actions)

The repository includes a GitHub Actions CI workflow in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) that:
1. Triggers on every `push` and `pull_request` targeting the `main` branch.
2. Boots an `ubuntu-latest` runner with Python `3.11`.
3. Installs dependencies from `requirements.txt`.
4. Executes `pytest -v --tb=short`.

---

## Injected Critical Bugs & Resolution Guide

This repository contains intentional critical bugs to demonstrate automated CI failure detection and reproduction:

### Bug A: Decimal vs Float Type Coercion (`TypeError`)
- **Location**: `ledger/checkout.py` in `calculate_tax()`
- **Symptom**:
  ```text
  TypeError: unsupported operand type(s) for *: 'decimal.Decimal' and 'float'
  ```
- **Cause**: Regional tax rates are retrieved as Python `float` (e.g. `0.08`), and multiplied directly against `taxable_subtotal` (`Decimal`). Python strictly disallows implicit coercion between `Decimal` and `float` to avoid rounding errors.
- **Resolution**:
  Convert `tax_rate` to `Decimal(str(tax_rate))` before multiplication:
  ```python
  tax_rate_decimal = Decimal(str(tax_rate))
  tax_amount = taxable_subtotal * tax_rate_decimal
  ```

### Bug B: In-Place List Mutation During Coupon Iteration (`Index Skipping`)
- **Location**: `ledger/checkout.py` in `apply_coupons()`
- **Symptom**:
  When multiple coupons are stacked and an expired coupon is removed via `self.coupons.remove(coupon)`, adjacent subsequent coupons are skipped, failing discount assertions and leaving expired coupons unpruned.
- **Cause**: Directly iterating over `self.coupons` while calling `remove()` mutates the list underlying the active iterator.
- **Resolution**:
  Iterate over a shallow copy of the list:
  ```python
  for coupon in list(self.coupons):
  ```
