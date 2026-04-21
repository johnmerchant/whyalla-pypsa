"""Parser for AEMO PLEXOS XML model files (Draft 2026 ISP and siblings).

The XML is a flat collection of tables; we do two streaming passes with
iterparse to keep memory low on the ~38 MB / 1.4 M-line files.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FlowStage:
    date_from: date | None  # inclusive start date (None = applies from model start)
    date_to: date | None    # inclusive end date (None = open-ended)
    value: float            # MW


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# PLEXOS namespace used in all ISP XML files.
_NS = "http://tempuri.org/MasterDataSet.xsd"


def _tag(local: str) -> str:
    return f"{{{_NS}}}{local}"


def _parse_date(text: str) -> date:
    """Accept 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS'."""
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return date.fromisoformat(text[:10])


def _child_text(elem: ET.Element, local: str) -> str | None:
    child = elem.find(_tag(local))
    return child.text if child is not None else None


# ---------------------------------------------------------------------------
# Pass-1: index classes / objects / properties / memberships
# ---------------------------------------------------------------------------

# Class name for transmission lines / interconnectors in PLEXOS schema.
_LINE_CLASS_NAME = "Line"
# Collection name that maps System → Line objects (collection used for Line properties).
_LINE_COLLECTION_NAME = "Lines"
# Property name we expose through load_interconnector_flows.
_DEFAULT_PROPERTY = "Max Flow"


def _build_index(xml_path: Path) -> dict:
    """Stream the XML once and return lookup dicts needed for data extraction."""
    class_id_by_name: dict[str, int] = {}
    object_name_by_id: dict[int, str] = {}
    object_class_by_id: dict[int, int] = {}
    # collection_id → (parent_class_id, child_class_id, name)
    collection_by_id: dict[int, tuple[int, int, str]] = {}
    # property_id → (collection_id, name)
    property_by_id: dict[int, tuple[int, str]] = {}
    # membership_id → (collection_id, child_object_id)
    membership_by_id: dict[int, tuple[int, int]] = {}

    for _event, elem in ET.iterparse(str(xml_path), events=("end",)):
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if local == "t_class":
            cid = _child_text(elem, "class_id")
            name = _child_text(elem, "name")
            if cid and name:
                class_id_by_name[name] = int(cid)
            elem.clear()

        elif local == "t_collection":
            col_id = _child_text(elem, "collection_id")
            p_cls = _child_text(elem, "parent_class_id")
            c_cls = _child_text(elem, "child_class_id")
            name = _child_text(elem, "name")
            if col_id and p_cls and c_cls and name:
                collection_by_id[int(col_id)] = (int(p_cls), int(c_cls), name)
            elem.clear()

        elif local == "t_object":
            oid = _child_text(elem, "object_id")
            cid = _child_text(elem, "class_id")
            name = _child_text(elem, "name")
            if oid and cid and name:
                object_name_by_id[int(oid)] = name
                object_class_by_id[int(oid)] = int(cid)
            elem.clear()

        elif local == "t_property":
            pid = _child_text(elem, "property_id")
            col_id = _child_text(elem, "collection_id")
            name = _child_text(elem, "name")
            if pid and col_id and name:
                property_by_id[int(pid)] = (int(col_id), name)
            elem.clear()

        elif local == "t_membership":
            mid = _child_text(elem, "membership_id")
            col_id = _child_text(elem, "collection_id")
            child_oid = _child_text(elem, "child_object_id")
            if mid and col_id and child_oid:
                membership_by_id[int(mid)] = (int(col_id), int(child_oid))
            elem.clear()

    return {
        "class_id_by_name": class_id_by_name,
        "object_name_by_id": object_name_by_id,
        "object_class_by_id": object_class_by_id,
        "collection_by_id": collection_by_id,
        "property_by_id": property_by_id,
        "membership_by_id": membership_by_id,
    }


# ---------------------------------------------------------------------------
# Pass-2: stream t_data / t_date_from / t_date_to for the target membership set
# ---------------------------------------------------------------------------


def _stream_data(
    xml_path: Path,
    target_membership_ids: frozenset[int],
    target_property_ids: frozenset[int],
) -> tuple[dict[int, float], dict[int, date], dict[int, date]]:
    """Return (data_values, date_from_map, date_to_map) for matching rows."""
    data_values: dict[int, float] = {}
    date_from_map: dict[int, date] = {}
    date_to_map: dict[int, date] = {}

    for _event, elem in ET.iterparse(str(xml_path), events=("end",)):
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if local == "t_data":
            mid_txt = _child_text(elem, "membership_id")
            pid_txt = _child_text(elem, "property_id")
            val_txt = _child_text(elem, "value")
            did_txt = _child_text(elem, "data_id")
            if mid_txt and pid_txt and val_txt and did_txt:
                mid = int(mid_txt)
                pid = int(pid_txt)
                if mid in target_membership_ids and pid in target_property_ids:
                    data_values[int(did_txt)] = float(val_txt)
            elem.clear()

        elif local == "t_date_from":
            # t_date_from rows appear after all t_data rows in the file, so
            # data_values is fully populated by the time we reach these tags.
            did_txt = _child_text(elem, "data_id")
            date_txt = _child_text(elem, "date")
            if did_txt and date_txt:
                did = int(did_txt)
                if did in data_values:
                    date_from_map[did] = _parse_date(date_txt)
            elem.clear()

        elif local == "t_date_to":
            did_txt = _child_text(elem, "data_id")
            date_txt = _child_text(elem, "date")
            if did_txt and date_txt:
                did = int(did_txt)
                if did in data_values:
                    date_to_map[did] = _parse_date(date_txt)
            elem.clear()

    return data_values, date_from_map, date_to_map


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_interconnectors(xml_path: str | Path) -> list[str]:
    """Return all Line object names (interconnectors) in the model."""
    xml_path = Path(xml_path)
    idx = _build_index(xml_path)

    line_class_id = idx["class_id_by_name"].get(_LINE_CLASS_NAME)
    if line_class_id is None:
        return []

    return sorted(
        name
        for oid, name in idx["object_name_by_id"].items()
        if idx["object_class_by_id"].get(oid) == line_class_id
    )


def load_interconnector_flows(
    xml_path: str | Path,
    interconnector_name: str,
    property: str = _DEFAULT_PROPERTY,
) -> list[FlowStage]:
    """Return staged flow limits for an interconnector, sorted by date_from.

    None-dated stages (baseline) come first.
    Raises KeyError if the interconnector or property is not found.
    """
    xml_path = Path(xml_path)
    idx = _build_index(xml_path)

    line_class_id = idx["class_id_by_name"].get(_LINE_CLASS_NAME)
    if line_class_id is None:
        raise KeyError(f"No class named '{_LINE_CLASS_NAME}' in {xml_path.name}")

    # Resolve object_id for the requested interconnector name.
    target_oid: int | None = None
    for oid, name in idx["object_name_by_id"].items():
        if name == interconnector_name and idx["object_class_by_id"].get(oid) == line_class_id:
            target_oid = oid
            break
    if target_oid is None:
        raise KeyError(f"Interconnector '{interconnector_name}' not found")

    # Find the System→Lines collection ids (parent_class_id=1, child_class_id=line_class_id).
    system_class_id = idx["class_id_by_name"].get("System", 1)
    line_collection_ids: frozenset[int] = frozenset(
        col_id
        for col_id, (p_cls, c_cls, _name) in idx["collection_by_id"].items()
        if p_cls == system_class_id and c_cls == line_class_id
    )

    # Find membership_ids linking System → our interconnector through a Line collection.
    target_membership_ids: frozenset[int] = frozenset(
        mid
        for mid, (col_id, child_oid) in idx["membership_by_id"].items()
        if child_oid == target_oid and col_id in line_collection_ids
    )
    if not target_membership_ids:
        raise KeyError(f"No System-scoped membership found for '{interconnector_name}'")

    # Resolve property_id(s) for the requested property name within Line collections.
    target_property_ids: frozenset[int] = frozenset(
        pid
        for pid, (col_id, pname) in idx["property_by_id"].items()
        if pname == property and col_id in line_collection_ids
    )
    if not target_property_ids:
        raise KeyError(f"Property '{property}' not found for Lines collection")

    # Stream data in a second pass.
    data_values, date_from_map, date_to_map = _stream_data(
        xml_path, target_membership_ids, target_property_ids
    )

    if not data_values:
        raise KeyError(
            f"No data found for '{interconnector_name}' / '{property}'"
        )

    # Build FlowStage list, deduplicating by (value, date_from, date_to) to
    # collapse rows that differ only by PLEXOS build tag.
    seen: set[tuple[float, date | None, date | None]] = set()
    stages: list[FlowStage] = []
    for did, value in data_values.items():
        df = date_from_map.get(did)
        dt = date_to_map.get(did)
        key = (value, df, dt)
        if key not in seen:
            seen.add(key)
            stages.append(FlowStage(date_from=df, date_to=dt, value=value))

    # Sort: None-dated (baseline) first, then ascending date_from.
    stages.sort(key=lambda s: (s.date_from is not None, s.date_from or date.min))
    return stages
