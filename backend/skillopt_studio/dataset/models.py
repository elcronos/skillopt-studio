"""Dataset request/response models for the dataset store + API.

The on-disk and over-the-wire shapes reuse the shared domain models
(``Dataset`` / ``DatasetCase``). These thin wrappers add the small request
payloads the store and API need without duplicating field semantics.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..domain import DatasetCase


class DatasetCreate(BaseModel):
    """Payload to create a dataset."""

    name: str
    cases: list[DatasetCase] = Field(default_factory=list)
    split_mode: Literal["ratio", "split_dir"] = "ratio"
    split_ratio: str = "2:1:7"


class DatasetSummary(BaseModel):
    """Lightweight listing entry (no full case bodies)."""

    name: str
    num_cases: int
    split_mode: str
    split_ratio: str
    path: Optional[str] = None


__all__ = ["DatasetCreate", "DatasetSummary"]
