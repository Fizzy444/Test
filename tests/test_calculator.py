"""Unit tests for calculator operations."""
import pytest
from calculator import add, subtract, multiply, divide

def test_add():
    assert add(2, 3) == 5

def test_subtract():
    assert subtract(10, 4) == 6

def test_multiply():
    assert multiply(3, 5) == 15

def test_divide_valid():
    assert divide(10, 2) == 5

def test_divide_by_zero():
    # Expects safe division behavior (returning 0 or handled result)
    # But current code crashes with ZeroDivisionError
    assert divide(10, 0) == 0
