import json
from pathlib import Path

from company_financials.models import CompanySnapshot, Coverage, Identity
from company_financials.storage.local import find_cached, load_snapshot, write_snapshot


def test_write_and_index(tmp_path: Path):
    snapshot = CompanySnapshot(
        identity=Identity(orgnr="123456789", name="Test AS"),
        coverage=Coverage(warnings=["demo"]),
    )
    folder = write_snapshot(tmp_path, snapshot, {"brreg_enhet": {"navn": "Test AS"}})
    assert (folder / "snapshot.json").exists()
    assert (folder / "financials.csv").exists()
    assert (folder / "snapshot.md").exists()
    assert (folder / "quality.md").exists()
    assert (folder / "manifest.json").exists()
    assert (folder / "sources" / "brreg_enhet.json").exists()
    assert (tmp_path / "index.json").exists()
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert index["companies"][0]["orgnr"] == "123456789"

    cached = find_cached(tmp_path, "123456789")
    assert cached == folder
    loaded = load_snapshot(folder)
    assert loaded.identity.name == "Test AS"
