"""Smoke test：验证 package 能被 import 且 schema_version 正确。"""
from rd_agent_contracts import SCHEMA_VERSION, __version__


def test_package_importable():
    assert __version__ == "1.0.0"


def test_schema_version_is_canonical():
    assert SCHEMA_VERSION == "1.0.0"
