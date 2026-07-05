"""Dynamic settings-form schema derived from a settings contract
(FRG-IDX-003, FRG-API-009).

Turns a Pydantic settings model into the full Sonarr Field-contract union —
``order, name, type, label, help, required, secret, selectOptions, advanced`` —
so the change-7 generic form renderer consumes it verbatim with zero
per-implementation frontend code. Fields come out in a stable declared order;
secret fields are flagged (``secret: true``) and their VALUES are never emitted
here (a schema template has no values to leak — write-only by construction).
"""

from __future__ import annotations

import types
import typing
from dataclasses import dataclass, field as dc_field
from typing import Any, Type

from pydantic import BaseModel, SecretStr

_NONE_TYPE = type(None)


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One renderable settings field (the Field-contract union)."""

    order: int
    name: str
    type: str
    label: str
    help: str
    required: bool
    secret: bool
    advanced: bool
    selectOptions: list[dict[str, Any]] = dc_field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "name": self.name,
            "type": self.type,
            "label": self.label,
            "help": self.help,
            "required": self.required,
            "secret": self.secret,
            "advanced": self.advanced,
            "selectOptions": list(self.selectOptions),
        }


def _is_secret(annotation: Any) -> bool:
    if annotation is SecretStr:
        return True
    return SecretStr in typing.get_args(annotation)


def _base_type(annotation: Any) -> Any:
    """Strip ``Optional`` (``X | None``) to ``X``; leave container types intact
    (``list[int]`` stays ``list[int]``, not ``int``)."""
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in typing.get_args(annotation) if a is not _NONE_TYPE]
        if len(args) == 1:
            return args[0]
    return annotation


def _field_type(annotation: Any, *, secret: bool) -> str:
    if secret:
        return "password"
    base = _base_type(annotation)
    origin = typing.get_origin(base)
    if origin in (list, set, tuple):
        return "select"  # multi-select (e.g. categories)
    if base is bool:
        return "checkbox"
    if base is int:
        return "number"
    return "textbox"


def schema_for(model: Type[BaseModel]) -> list[FieldSpec]:
    """Derive the ordered ``fields[]`` metadata for one settings model."""
    specs: list[FieldSpec] = []
    for order, (name, info) in enumerate(model.model_fields.items()):
        extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
        secret = _is_secret(info.annotation)
        specs.append(
            FieldSpec(
                order=order,
                name=name,
                type=_field_type(info.annotation, secret=secret),
                label=str(extra.get("label", name)),
                help=str(extra.get("help", info.description or "")),
                required=info.is_required(),
                secret=secret,
                advanced=bool(extra.get("advanced", False)),
                selectOptions=list(extra.get("selectOptions", [])),
            )
        )
    return specs
