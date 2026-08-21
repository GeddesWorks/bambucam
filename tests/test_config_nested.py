"""Nested config sections must become dataclasses, not raw dicts.

A section missing from _NESTED_TYPES loads as a plain dict and everything
looks fine until the daemon does config.upload.nas.dir at startup and dies
with AttributeError. Unit tests that build backends directly never catch it.
"""
import dataclasses

import pytest

from bambucam.config import _NESTED_TYPES, BambuCamConfig, _build_dataclass


def _nested_dataclass_fields():
    """Every dataclass-typed field on any config section, by field name."""
    seen, out = set(), []
    stack = [BambuCamConfig]
    while stack:
        cls = stack.pop()
        if cls in seen or not dataclasses.is_dataclass(cls):
            continue
        seen.add(cls)
        for f in dataclasses.fields(cls):
            if dataclasses.is_dataclass(f.type) or (
                isinstance(f.type, type) and dataclasses.is_dataclass(f.type)
            ):
                out.append((cls.__name__, f.name, f.type))
                stack.append(f.type)
    return out


@pytest.mark.parametrize("section", ["nas", "appwrite", "http"])
def test_known_sections_are_registered(section):
    assert section in _NESTED_TYPES


def test_every_nested_dataclass_field_is_registered():
    missing = [
        f"{owner}.{name}"
        for owner, name, _ in _nested_dataclass_fields()
        if name not in _NESTED_TYPES
    ]
    assert not missing, (
        f"nested config sections not in _NESTED_TYPES: {missing} — "
        "these load as plain dicts and crash the daemon at startup"
    )


def test_nas_section_builds_a_dataclass_not_a_dict():
    from bambucam.config import UploadConfig

    cfg = _build_dataclass(UploadConfig, {
        "backend": "nas",
        "nas": {"dir": "/mnt/nas/BambuCam", "mount_point": "/mnt/nas"},
    })
    assert cfg.nas.dir == "/mnt/nas/BambuCam"
    assert cfg.nas.mount_point == "/mnt/nas"
