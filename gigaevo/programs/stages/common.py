from __future__ import annotations

from typing import Any, TypeVar

from pydantic import Field

from gigaevo.programs.core_types import StageIO

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


class Box[T](StageIO):
    """Generic single-value container: { data: T }."""

    data: T


class ProgramPayload(Box[T]):
    """Program execution output plus a stable semantic cache identity."""

    payload_hash: str
    provenance: dict[str, str] = Field(default_factory=dict)


class ListOf[T](StageIO):
    """Generic list container: { items: list[T] }."""

    items: list[T]


String = Box[str]
AnyContainer = Box[Any]
ProgramPayloadContainer = ProgramPayload[Any]
StringContainer = Box[str]
FloatDictContainer = Box[dict[str, float]]
DictContainer = Box[dict[str, Any]]
# Backward-compat alias for validator stage outputs stored via cloudpickle.
ValidatorOutput = Box[tuple[dict[str, float], Any]]

StringList = ListOf[str]
FloatDictList = ListOf[dict[str, float]]
