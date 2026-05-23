"""FeatureCatalog — YAML-driven catalog of SAE features.

A catalog lists candidate features (id, label, source, suggested threshold)
for a given SAE artifact. It is *not* a policy by itself; users select a subset
of features into their policy.

The catalog ships with zero hardcoded feature IDs by default. Users construct
catalogs from Goodfire feature explorer, Neuronpedia, or their own labelling.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class FeatureEntry:
    feature_id: int
    label: str = ""
    source: str = ""
    suggested_threshold: float = 0.5
    note: str = ""


@dataclass
class FeatureCatalog:
    sae_model_id: str = ""
    layer: int = 0
    entries: list[FeatureEntry] = field(default_factory=list)

    def __iter__(self) -> Iterator[FeatureEntry]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def by_id(self, feature_id: int) -> FeatureEntry | None:
        for e in self.entries:
            if e.feature_id == feature_id:
                return e
        return None

    def ids(self) -> list[int]:
        return [e.feature_id for e in self.entries]


def load_catalog(path: str | Path) -> FeatureCatalog:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"catalog not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return catalog_from_dict(raw)


def catalog_from_dict(raw: Mapping[str, Any]) -> FeatureCatalog:
    if not isinstance(raw, Mapping):
        raise ValueError("catalog YAML must be a mapping")
    sae_model_id = str(raw.get("sae_model_id", ""))
    layer = int(raw.get("layer", 0))
    entries_raw = raw.get("entries", [])
    if not isinstance(entries_raw, list):
        raise ValueError("catalog.entries must be a list")
    entries: list[FeatureEntry] = []
    seen: set[int] = set()
    for i, e in enumerate(entries_raw):
        if not isinstance(e, Mapping):
            raise ValueError(f"entry[{i}] must be a mapping")
        if "feature_id" not in e:
            raise ValueError(f"entry[{i}] missing feature_id")
        fid = int(e["feature_id"])
        if fid in seen:
            raise ValueError(f"entry[{i}] duplicate feature_id {fid}")
        seen.add(fid)
        entries.append(
            FeatureEntry(
                feature_id=fid,
                label=str(e.get("label", "")),
                source=str(e.get("source", "")),
                suggested_threshold=float(e.get("suggested_threshold", 0.5)),
                note=str(e.get("note", "")),
            )
        )
    return FeatureCatalog(sae_model_id=sae_model_id, layer=layer, entries=entries)
