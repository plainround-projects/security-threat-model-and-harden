"""The threat model cannot drift from the suite: every fixed threat links a test that exists."""

import re
from itertools import takewhile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = (ROOT / "docs" / "THREAT_MODEL.md").read_text()
TEST_REFERENCE = re.compile(r"`(tests/[\w/]+\.py)::(\w+)`")


def _table_rows(heading: str) -> list[list[str]]:
    """The body rows of the first table under a heading."""
    lines = iter(DOCUMENT.split(heading, 1)[1].splitlines())
    table = []
    for line in lines:
        if line.startswith("|"):
            table.append(line)
            table.extend(takewhile(lambda row: row.startswith("|"), lines))
            break
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in table]
    return rows[2:]  # drop the header and its separator


def test_every_boundary_has_at_least_one_threat():
    boundaries = {row[1] for row in _table_rows("## Verification note")}
    assert boundaries == {"B1", "B2", "B3"}


def test_every_fixed_threat_links_a_test_that_exists():
    rows = _table_rows("## Verification note")
    assert len(rows) >= 20
    for threat_id, _boundary, _stride, _threat, control, proof, status in rows:
        assert status == "fixed", threat_id
        assert control, threat_id
        references = TEST_REFERENCE.findall(proof)
        assert references, f"{threat_id} names no test"
        for path, name in references:
            source = (ROOT / path).read_text()
            assert re.search(rf"^def {name}\(", source, re.MULTILINE), f"{threat_id}: {path}::{name} does not exist"


def test_threat_ids_are_unique_and_sequential():
    ids = [row[0] for row in _table_rows("## Verification note")]
    assert ids == [f"T{number}" for number in range(1, len(ids) + 1)]


def test_at_least_one_threat_is_accepted_with_a_reason():
    accepted = _table_rows("## Accepted risks")
    assert accepted
    assert all(len(row[2]) > 40 for row in accepted)
    assert accepted[0][0] == "A1"
