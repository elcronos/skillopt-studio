"""Datasets CRUD API.

``router`` exposes list/get/create/delete over the filesystem-backed dataset
store. Datasets are the self-contained ``{id,input,ground_truth,metadata}``
payloads consumed by the generic_qa adapter.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..dataset import models as dataset_models
from ..dataset import store as dataset_store
from ..domain import Dataset

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.get("")
def list_datasets() -> list[dataset_models.DatasetSummary]:
    """List all datasets (summaries only)."""
    return dataset_store.list_datasets()


@router.get("/{name}")
def get_dataset(name: str) -> Dataset:
    """Return a full dataset by name/slug."""
    ds = dataset_store.get(name)
    if ds is None:
        raise HTTPException(status_code=404, detail=f"dataset '{name}' not found")
    return ds


@router.post("", status_code=201)
def create_dataset(payload: dataset_models.DatasetCreate) -> dataset_models.DatasetSummary:
    """Create (or overwrite) a dataset."""
    dataset = Dataset(
        name=payload.name,
        cases=payload.cases,
        split_mode=payload.split_mode,
        split_ratio=payload.split_ratio,
    )
    return dataset_store.create(dataset)


@router.delete("/{name}")
def delete_dataset(name: str) -> dict[str, bool]:
    """Delete a dataset. 404 if it does not exist."""
    if not dataset_store.delete(name):
        raise HTTPException(status_code=404, detail=f"dataset '{name}' not found")
    return {"deleted": True}
