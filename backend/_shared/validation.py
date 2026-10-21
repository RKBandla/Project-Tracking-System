"""
Declarative request-body validation.

Each service declares a dict of ``Field`` specs; ``validate`` returns cleaned
values or raises a 400 listing every invalid field.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import bad_request

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Field:
    """Specification for one input field."""

    kind: str = "str"  # str | text | email | int | decimal | date | bool
    required: bool = False
    nullable: bool = False
    max_length: int = 255
    choices: tuple = ()
    min_value: float | None = None
    max_value: float | None = None


def _clean(name: str, value: Any, spec: Field) -> Any:
    """Convert and check a single value, raising ValueError with a message."""
    if value is None or (isinstance(value, str) and not value.strip() and spec.kind != "text"):
        if spec.required and not spec.nullable:
            raise ValueError("is required")
        return None

    if spec.kind in ("str", "text", "email"):
        if not isinstance(value, str):
            raise ValueError("must be a string")
        value = value.strip()
        if len(value) > spec.max_length:
            raise ValueError(f"must be at most {spec.max_length} characters")
        if spec.kind == "email":
            value = value.lower()
            if not EMAIL_RE.match(value):
                raise ValueError("must be a valid email address")
        if spec.choices and value not in spec.choices:
            raise ValueError(f"must be one of: {', '.join(spec.choices)}")
        return value

    if spec.kind == "int":
        if isinstance(value, bool):
            raise ValueError("must be an integer")
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("must be an integer") from exc
        if isinstance(value, float) and value != number:
            raise ValueError("must be an integer")
        _check_range(number, spec)
        return number

    if spec.kind == "decimal":
        if isinstance(value, bool):
            raise ValueError("must be a number")
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("must be a number") from exc
        if not number.is_finite():
            raise ValueError("must be a number")
        _check_range(number, spec)
        return number.quantize(Decimal("0.01"))

    if spec.kind == "date":
        if not isinstance(value, str):
            raise ValueError("must be a date (YYYY-MM-DD)")
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError("must be a date (YYYY-MM-DD)") from exc

    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise ValueError("must be true or false")
        return value

    raise ValueError(f"has unknown type {spec.kind}")  # pragma: no cover


def _check_range(number: Any, spec: Field) -> None:
    """Check numeric bounds."""
    if spec.min_value is not None and number < spec.min_value:
        raise ValueError(f"must be at least {spec.min_value:g}")
    if spec.max_value is not None and number > spec.max_value:
        raise ValueError(f"must be at most {spec.max_value:g}")


def validate(data: dict, schema: dict[str, Field], partial: bool = False) -> dict:
    """
    Validate ``data`` against ``schema``.

    Args:
        data: The request body.
        schema: Field specs keyed by field name.
        partial: When True (updates), only fields present in ``data`` are checked
            and required fields may be omitted.

    Returns:
        dict: Cleaned values for the fields that were provided (all schema
        fields for a full validation).
    """
    errors: dict[str, str] = {}
    unknown = sorted(set(data) - set(schema))
    for name in unknown:
        errors[name] = "is not an allowed field"

    cleaned: dict[str, Any] = {}
    for name, spec in schema.items():
        if partial and name not in data:
            continue
        try:
            cleaned[name] = _clean(name, data.get(name), spec)
        except ValueError as exc:
            errors[name] = str(exc)

    if errors:
        raise bad_request("Validation failed", errors)
    return cleaned


def check_date_range(start: date | None, end: date | None, start_name: str = "start_date",
                     end_name: str = "end_date") -> None:
    """Raise 400 if an end date is before its start date."""
    if start and end and end < start:
        raise bad_request("Validation failed", {end_name: f"must be on or after {start_name}"})
