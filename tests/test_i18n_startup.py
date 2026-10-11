"""Installer handoff, task identity, and translation call contracts."""

import ast
from pathlib import Path
from string import Formatter

from signum.ai.model_profiles import ModelProfile
from signum.app import _initialize_language
from signum.config import AppConfig
from signum.core.classification import (
    DEFAULT_CATEGORIES,
    DEFAULT_INSTRUCTIONS,
    example_categories,
    make_question,
)
from signum.core.classification_calibration import policy_for
from signum.i18n import catalog, get_language, set_language


def test_installer_language_only_sets_first_launch_preference() -> None:
    _initialize_language(["--language", "en"])
    assert get_language() == "en"
    assert AppConfig.load().language == "en"
    _initialize_language(["--language", "pl"])
    assert get_language() == "en"
    assert AppConfig.load().language == "en"


def test_read_only_setup_does_not_create_preferences(isolated_config: Path) -> None:
    _initialize_language(["--setup-local-ai", "--check-only", "--language", "en"])
    assert not isolated_config.exists()


def test_english_examples_do_not_inherit_polish_calibration() -> None:
    model = ModelProfile(id="gemma", model="gemma4:12b")
    original = make_question(list(DEFAULT_CATEGORIES), DEFAULT_INSTRUCTIONS)
    assert policy_for(model, original)
    set_language("en")
    english = make_question(list(example_categories()), DEFAULT_INSTRUCTIONS)
    assert english != original
    assert policy_for(model, english) == {}
    model.threshold, model.hitl_margin = 0.65, 0.05
    assert policy_for(model, english)["id"] == "user-defined"


def test_translation_calls_supply_the_catalog_placeholders() -> None:
    root = Path(__file__).resolve().parents[1] / "src/signum"
    entries = catalog()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Name)
                or node.func.id != "tr"
                or not node.args
                or not isinstance(node.args[0], ast.Constant)
            ):
                continue
            key = node.args[0].value
            if key.startswith("prompt."):
                continue  # literal JSON braces, not formatting arguments
            fields = {
                name for _, name, _, _ in Formatter().parse(entries[key]["pl"]) if name is not None
            }
            supplied = {arg.arg for arg in node.keywords}
            assert fields == supplied, f"{path}:{node.lineno}: {fields} != {supplied}"
