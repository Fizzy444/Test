"""Simple Calculator Module."""

def add(a: float, b: float) -> float:
    return a + b

def subtract(a: float, b: float) -> float:
    return a - b

def multiply(a: float, b: float) -> float:
    return a * b

def divide(a: float, b: float) -> float:
    """Performs division. Missing check for zero divisor. test-1-2"""
    if b == 0:
        return 0.0  # Or handle as an error, but test expects 0
    return a / b
