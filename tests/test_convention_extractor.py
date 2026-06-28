"""Tests for src/optimusprime/convention_extractor.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from optimusprime.convention_extractor import Convention, ConventionExtractor


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a minimal Python project structure."""
    src = tmp_path / "src" / "myapp"
    src.mkdir(parents=True)
    (tmp_path / "tests").mkdir()

    # Python source files using try/except
    (src / "auth.py").write_text(
        "def login(user, pwd):\n    try:\n        return db.get(user)\n    except Exception as e:\n        raise ValueError(e)\n"
    )
    (src / "api.py").write_text(
        "def get_user(uid):\n    try:\n        return db.query(uid)\n    except Exception:\n        return None\n"
    )
    (src / "utils.py").write_text(
        "import os\nimport re\nfrom pathlib import Path\n\ndef parse_date(s):\n    return s.split('-')\n"
    )

    # Test files
    (tmp_path / "tests" / "test_auth.py").write_text(
        "import pytest\nfrom myapp.auth import login\n\ndef test_login(): pass\n"
    )
    (tmp_path / "tests" / "test_utils.py").write_text(
        "import pytest\nfrom myapp.utils import parse_date\n\ndef test_parse(): pass\n"
    )

    return tmp_path


@pytest.fixture
def op_dir(tmp_path: Path) -> Path:
    op = tmp_path / ".optimusprime"
    op.mkdir()
    return op


# ---- 1. extract() returns conventions ----------------------------------

def test_extract_returns_list_of_conventions(project_dir, op_dir):
    ce = ConventionExtractor(project_dir, op_dir)
    result = ce.extract()
    assert isinstance(result, list)
    assert len(result) > 0


def test_extract_all_items_are_convention_instances(project_dir, op_dir):
    ce = ConventionExtractor(project_dir, op_dir)
    result = ce.extract()
    assert all(isinstance(c, Convention) for c in result)


# ---- 2. conventions.json written to op_dir ----------------------------

def test_extract_writes_conventions_json(project_dir, op_dir):
    ce = ConventionExtractor(project_dir, op_dir)
    ce.extract()
    conv_path = op_dir / "conventions.json"
    assert conv_path.is_file()


def test_conventions_json_valid_structure(project_dir, op_dir):
    ce = ConventionExtractor(project_dir, op_dir)
    ce.extract()
    data = json.loads((op_dir / "conventions.json").read_text())
    assert "conventions" in data
    assert "version" in data
    assert isinstance(data["conventions"], list)


# ---- 3. Testing conventions detected ----------------------------------

def test_testing_convention_detected(project_dir, op_dir):
    ce = ConventionExtractor(project_dir, op_dir)
    conventions = ce.extract()
    cats = [c.category for c in conventions]
    assert "testing" in cats


def test_testing_convention_has_evidence(project_dir, op_dir):
    ce = ConventionExtractor(project_dir, op_dir)
    conventions = ce.extract()
    testing = [c for c in conventions if c.category == "testing"]
    assert testing[0].evidence_count > 0
    assert testing[0].confidence >= 0.5


# ---- 4. Error handling detected ---------------------------------------

def test_error_handling_convention_detected(project_dir, op_dir):
    ce = ConventionExtractor(project_dir, op_dir)
    conventions = ce.extract()
    cats = [c.category for c in conventions]
    assert "error_handling" in cats


# ---- 5. Structure detected --------------------------------------------

def test_src_structure_detected(project_dir, op_dir):
    ce = ConventionExtractor(project_dir, op_dir)
    conventions = ce.extract()
    structure = [c for c in conventions if c.category == "structure"]
    assert len(structure) > 0
    assert any("src" in c.rule.lower() for c in structure)


# ---- 6. get_violations() returns list ---------------------------------

def test_get_violations_returns_list(project_dir, op_dir):
    ce = ConventionExtractor(project_dir, op_dir)
    ce.extract()
    violations = ce.get_violations("def myFunc(): pass\n", "auth.py")
    assert isinstance(violations, list)


def test_get_violations_empty_when_no_conventions_json(tmp_path, op_dir):
    ce = ConventionExtractor(tmp_path, op_dir)
    violations = ce.get_violations("from foo import *\n", "bar.py")
    assert violations == []


# ---- 7. Star import violation detected --------------------------------

def test_star_import_violation_detected(project_dir, op_dir):
    ce = ConventionExtractor(project_dir, op_dir)
    ce.extract()

    # Check if no-star-imports convention was extracted
    data = json.loads((op_dir / "conventions.json").read_text())
    no_star = [c for c in data["conventions"] if "star" in c.get("rule", "").lower()]
    if not no_star:
        pytest.skip("No star import convention extracted from this project")

    violations = ce.get_violations("from os import *\nx = path\n", "utils.py")
    assert any("star" in v.lower() for v in violations)


# ---- 8. Empty project does not crash ----------------------------------

def test_empty_project_no_crash(tmp_path, op_dir):
    ce = ConventionExtractor(tmp_path, op_dir)
    result = ce.extract()
    assert isinstance(result, list)


# ---- 9. Conventions sorted by confidence descending ------------------

def test_conventions_sorted_by_confidence_desc(project_dir, op_dir):
    ce = ConventionExtractor(project_dir, op_dir)
    conventions = ce.extract()
    if len(conventions) < 2:
        return
    confidences = [c.confidence for c in conventions]
    assert confidences == sorted(confidences, reverse=True)


# ---- 10. Convention dataclass has all required fields -----------------

def test_convention_dataclass_fields(project_dir, op_dir):
    ce = ConventionExtractor(project_dir, op_dir)
    conventions = ce.extract()
    if not conventions:
        pytest.skip("No conventions extracted")
    c = conventions[0]
    assert hasattr(c, "category")
    assert hasattr(c, "rule")
    assert hasattr(c, "confidence")
    assert hasattr(c, "evidence_count")
    assert hasattr(c, "examples")
    assert isinstance(c.examples, list)
