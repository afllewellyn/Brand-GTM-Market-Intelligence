"""Output helpers: JSON/CSV/Markdown writers and run metadata."""

from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path
from typing import Any

from .schemas.evidence import EvidenceRow


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(path: Path, data: Any) -> Path:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def write_evidence_csv(path: Path, rows: list[EvidenceRow]) -> Path:
    fields = list(EvidenceRow.model_fields)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.model_dump())
    return path


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]
