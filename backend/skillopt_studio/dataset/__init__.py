"""Dataset CRUD for the generic_qa adapter.

``store`` persists self-contained ``dataset.json`` files (and an optional
``split_dir`` layout) under ``configs/datasets/<slug>/``; ``models`` holds the
request/summary payloads used by the store and the datasets API.
"""

from .store import create, get, list_datasets, delete, data_path, DATASETS_DIR
from .models import DatasetCreate, DatasetSummary

__all__ = [
    "create",
    "get",
    "list_datasets",
    "delete",
    "data_path",
    "DATASETS_DIR",
    "DatasetCreate",
    "DatasetSummary",
]
