import os

import pytest

from bambucam.config import BambuCamConfig, load_config


def test_default_config():
    config = BambuCamConfig()
    assert config.trigger.gpio_pin == 17
    assert config.camera.timeout_seconds == 30
    assert config.compile.fps == 30
    assert config.printer.http.listen_port == 8420


def test_load_missing_config(tmp_path):
    config = load_config(tmp_path / "nonexistent.yaml")
    assert config.trigger.gpio_pin == 17


def test_load_yaml_config(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
trigger:
  gpio_pin: 27
  edge: falling
camera:
  timeout_seconds: 15
compile:
  fps: 24
""")
    config = load_config(config_file)
    assert config.trigger.gpio_pin == 27
    assert config.trigger.edge == "falling"
    assert config.camera.timeout_seconds == 15
    assert config.compile.fps == 24


def test_env_var_substitution(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_ENDPOINT", "https://cloud.appwrite.io/v1")
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
upload:
  backend: appwrite
  appwrite:
    endpoint: ${TEST_ENDPOINT}
""")
    config = load_config(config_file)
    assert config.upload.appwrite.endpoint == "https://cloud.appwrite.io/v1"


def test_missing_env_var(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
upload:
  appwrite:
    endpoint: ${DOES_NOT_EXIST}
""")
    with pytest.raises(ValueError, match="DOES_NOT_EXIST"):
        load_config(config_file)
