"""Regression guards for Home Assistant device area assignments."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


ENTITY_BASE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "eltako_sensors_actuators"
    / "entity_base.py"
)


class TestAreaAssignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = ENTITY_BASE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def _entity_class(self, name: str) -> ast.ClassDef:
        for node in self.tree.body:
            if isinstance(node, ast.ClassDef) and node.name == name:
                return node
        self.fail(f"Missing entity class: {name}")

    def test_device_info_suggests_imported_area(self) -> None:
        base = self._entity_class("EltakoBaseEntity")
        device_info = next(
            node
            for node in base.body
            if isinstance(node, ast.FunctionDef) and node.name == "device_info"
        )
        source = ast.get_source_segment(self.source, device_info) or ""
        self.assertIn('_device_option(self.device_config, "area", "")', source)
        self.assertIn("suggested_area=suggested_area", source)

    def test_yaml_entity_does_not_reassign_area_after_creation(self) -> None:
        yaml_entity = self._entity_class("EltakoYamlEntity")
        self.assertFalse(
            any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "async_added_to_hass"
                for node in yaml_entity.body
            ),
            "Manual area changes must survive Home Assistant restarts and reloads",
        )


if __name__ == "__main__":
    unittest.main()
