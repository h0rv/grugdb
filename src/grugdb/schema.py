"""Check field values against their declared types at runtime."""

import builtins
import types
import typing
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

SCALARS = (types.NoneType, bool, int, float, str, bytes, date, datetime, Decimal)


def resolve(hint: object) -> object:
    """Unwrap `type` aliases and `NewType` to the runtime shape they stand for."""
    while True:
        if hint is None:
            return types.NoneType
        if isinstance(hint, typing.TypeAliasType):
            hint = hint.__value__
        elif isinstance(hint, typing.NewType):
            hint = hint.__supertype__
        else:
            return hint


def is_variadic(args: tuple[object, ...]) -> bool:
    return len(args) == 2 and args[1] is Ellipsis


def validate_hint(hint: object) -> None:
    """Raise `TypeError` unless values of `hint` are immutable and supported."""
    from grugdb.model import Row

    hint = resolve(hint)
    args = typing.get_args(hint)
    match typing.get_origin(hint):
        case typing.Union | types.UnionType | builtins.frozenset:
            for arg in args:
                validate_hint(arg)
        case builtins.tuple:
            for arg in args[:1] if is_variadic(args) else args:
                validate_hint(arg)
        case typing.Literal:
            if not all(type(arg) in SCALARS or isinstance(arg, Enum) for arg in args):
                raise TypeError(f"unsupported literal in {hint}")
        case None if hint in SCALARS:
            pass
        case None if isinstance(hint, type) and issubclass(hint, Row) and hint is not Row:
            pass
        case None if isinstance(hint, type) and issubclass(hint, Enum):
            if not all(type(member.value) in SCALARS for member in hint):
                raise TypeError(f"enum {hint.__name__} has unsupported values")
        case _:
            raise TypeError(f"unsupported annotation: {hint}")


def matches(value: object, hint: object) -> bool:
    """Return whether `value` has exactly the declared type `hint`."""
    hint = resolve(hint)
    validate_hint(hint)
    args = typing.get_args(hint)
    match typing.get_origin(hint):
        case typing.Union | types.UnionType:
            return any(matches(value, arg) for arg in args)
        case typing.Literal:
            return any(type(value) is type(arg) and value == arg for arg in args)
        case builtins.tuple if is_variadic(args):
            return type(value) is tuple and all(matches(item, args[0]) for item in value)
        case builtins.tuple:
            return (
                type(value) is tuple
                and len(value) == len(args)
                and all(matches(item, arg) for item, arg in zip(value, args, strict=True))
            )
        case builtins.frozenset:
            return type(value) is frozenset and all(matches(item, args[0]) for item in value)
        case _ if hint is float:
            return type(value) in (int, float)
        case _:
            return type(value) is hint
