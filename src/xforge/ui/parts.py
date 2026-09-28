"""Part search and acquisition.

Searching is the one place xforge deliberately goes online. The rule that
keeps that from undermining reproducible builds is: online to acquire,
vendored to build. A part is fetched once, converted, and written into the
project's own library; every build afterwards reads the vendored copy and
needs no network.

So `search` and `fetch` talk to the supplier. Everything downstream reads
what they left behind.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class PartsError(RuntimeError):
    """Something went wrong talking to the supplier, said in plain terms."""


class SupplierUnavailable(PartsError):
    """The supplier could not be reached, or the extra is not installed."""


@dataclass(frozen=True)
class PriceBreak:
    qty: int
    price: float


@dataclass
class Part:
    """One search result, normalised away from any supplier's field names."""

    lcsc: str
    mpn: str
    brand: str
    package: str
    category: str = ""
    description: str = ""
    stock: int = 0
    price: float | None = None
    price_breaks: list[PriceBreak] = field(default_factory=list)
    min_qty: int | None = None
    basic: bool = False  # JLC "Basic" parts carry no loading fee
    datasheet: str | None = None
    url: str | None = None

    @property
    def orderable(self) -> bool:
        return self.stock > 0

    def price_at(self, qty: int) -> float | None:
        """Unit price at a build quantity, from the break table."""
        applicable = [b for b in self.price_breaks if b.qty <= qty]
        if applicable:
            return max(applicable, key=lambda b: b.qty).price
        return self.price

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["orderable"] = self.orderable
        return d


def _api():
    """The supplier client, imported late so the extra stays optional."""
    try:
        from easyeda2kicad.easyeda.easyeda_api import EasyedaApi
    except ImportError as exc:
        raise SupplierUnavailable(
            "Part search needs the 'parts' extra. Install it with:\n"
            "    pip install -e \".[parts]\""
        ) from exc
    return EasyedaApi()


def _part_from_row(row: dict[str, Any]) -> Part:
    breaks = [
        PriceBreak(qty=int(b.get("qty", 0)), price=float(b.get("price", 0)))
        for b in (row.get("price_breaks") or [])
        if b.get("qty") is not None
    ]
    return Part(
        lcsc=str(row.get("lcsc") or ""),
        mpn=str(row.get("model") or row.get("name") or ""),
        brand=str(row.get("brand") or ""),
        package=str(row.get("package") or ""),
        category=str(row.get("category") or ""),
        description=str(row.get("description") or ""),
        stock=int(row.get("stock") or 0),
        price=(float(row["price"]) if row.get("price") is not None else None),
        price_breaks=sorted(breaks, key=lambda b: b.qty),
        min_qty=(int(row["min_qty"]) if row.get("min_qty") is not None else None),
        basic=str(row.get("type") or "").lower() == "basic",
        datasheet=row.get("datasheet"),
        url=row.get("url"),
    )


def search(keyword: str, page: int = 1, page_size: int = 25) -> tuple[int, list[Part]]:
    """Search the supplier catalogue. Returns (total matches, this page)."""
    keyword = (keyword or "").strip()
    if not keyword:
        return 0, []
    try:
        raw = _api().search_jlcpcb_components(
            keyword=keyword, page=page, page_size=page_size
        )
    except SupplierUnavailable:
        raise
    except Exception as exc:
        raise PartsError(
            f"Search failed talking to the supplier: {type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise PartsError(f"Supplier returned {type(raw).__name__}, expected an object")
    rows = raw.get("results") or []
    return int(raw.get("total") or len(rows)), [_part_from_row(r) for r in rows]


def detail(lcsc: str) -> dict[str, Any]:
    """Full CAD data for one part, including whether a 3D model exists."""
    lcsc = (lcsc or "").strip().upper()
    if not lcsc:
        raise PartsError("No LCSC id given")
    try:
        data = _api().get_cad_data_of_component(lcsc_id=lcsc)
    except SupplierUnavailable:
        raise
    except Exception as exc:
        raise PartsError(f"Lookup failed for {lcsc}: {exc}") from exc
    if not data:
        raise PartsError(
            f"{lcsc} returned no CAD data. Check the id, or the part may have "
            "no EasyEDA footprint."
        )
    head = (data.get("dataStr") or {}).get("head", {}).get("c_para", {})
    return {
        "lcsc": lcsc,
        "mpn": head.get("Manufacturer Part"),
        "brand": head.get("Manufacturer"),
        "package": head.get("package"),
        "has_3d": bool(data.get("packageDetail")),
        "raw": data,
    }


# ── vendoring ─────────────────────────────────────────────────────────


@dataclass
class VendoredPart:
    lcsc: str
    mpn: str
    directory: Path
    files: list[str]
    fetched: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["directory"] = str(self.directory)
        return d


class Library:
    """The project's vendored part library and its lockfile.

    Everything here is on disk and under version control. The lockfile records
    what was fetched and when, so a build two years from now resolves to the
    same parts without asking a supplier anything.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.parts_dir = self.root / "parts"
        self.lockfile = self.root / "parts.lock.json"

    def load(self) -> dict[str, dict]:
        if not self.lockfile.exists():
            return {}
        try:
            return json.loads(self.lockfile.read_text(encoding="utf-8")).get(
                "parts", {}
            )
        except json.JSONDecodeError as exc:
            raise PartsError(
                f"{self.lockfile.name} is not valid JSON: {exc}"
            ) from exc

    def save(self, parts: dict[str, dict]) -> None:
        self.lockfile.parent.mkdir(parents=True, exist_ok=True)
        self.lockfile.write_text(
            json.dumps(
                {"schema": "xforge.parts.lock/1", "parts": parts}, indent=2
            ),
            encoding="utf-8",
        )

    def has(self, lcsc: str) -> bool:
        return lcsc.upper() in self.load()

    def vendor(self, lcsc: str, symbol: bool = True, footprint: bool = True,
               model_3d: bool = True) -> VendoredPart:
        """Fetch a part and write it into the project library.

        Uses easyeda2kicad's converters so the output is a normal KiCad
        symbol, footprint and 3D model that any tool can read - the point of
        vendoring is that nothing downstream depends on xforge.
        """
        lcsc = lcsc.strip().upper()
        info = detail(lcsc)
        target = self.parts_dir / lcsc
        target.mkdir(parents=True, exist_ok=True)

        written: list[str] = []
        try:
            from easyeda2kicad.easyeda.easyeda_importer import (
                Easyeda3dModelImporter,
                EasyedaFootprintImporter,
                EasyedaSymbolImporter,
            )
            from easyeda2kicad.kicad.export_kicad_3d_model import Exporter3dModelKicad
            from easyeda2kicad.kicad.export_kicad_footprint import (
                ExporterFootprintKicad,
            )
            from easyeda2kicad.kicad.export_kicad_symbol import ExporterSymbolKicad
        except ImportError as exc:
            raise SupplierUnavailable(
                "Vendoring needs the 'parts' extra: pip install -e \".[parts]\""
            ) from exc

        raw = info["raw"]
        if symbol:
            sym = EasyedaSymbolImporter(easyeda_cp_cad_data=raw).get_symbol()
            out = target / f"{lcsc}.kicad_sym"
            # export() returns the library text; the caller owns the file.
            out.write_text(
                ExporterSymbolKicad(symbol=sym).export(footprint_lib_name=lcsc),
                encoding="utf-8",
            )
            written.append(out.name)

        if footprint:
            fp = EasyedaFootprintImporter(easyeda_cp_cad_data=raw).get_footprint()
            out = target / f"{lcsc}.kicad_mod"
            # This exporter writes the file itself and returns None.
            ExporterFootprintKicad(footprint=fp).export(
                footprint_full_path=str(out), model_3d_path=str(target)
            )
            if out.exists():
                written.append(out.name)

        if model_3d and info["has_3d"]:
            try:
                model = Easyeda3dModelImporter(
                    easyeda_cp_cad_data=raw, download_raw_3d_model=True
                ).create_3d_model()
                if model is not None:
                    Exporter3dModelKicad(model_3d=model).export(str(target))
                    written.extend(
                        p.name
                        for p in target.rglob("*")
                        if p.suffix.lower() in (".wrl", ".step", ".stp")
                    )
            except Exception as exc:
                # A missing 3D model is not a reason to fail an import: the
                # symbol and footprint are what a netlist and a board need.
                # Record why rather than swallowing it silently.
                written.append(f"(no 3D model: {type(exc).__name__})")

        record = VendoredPart(
            lcsc=lcsc,
            mpn=info.get("mpn") or "",
            directory=target,
            files=sorted(set(written)),
            fetched=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        parts = self.load()
        parts[lcsc] = record.to_dict()
        self.save(parts)
        return record
