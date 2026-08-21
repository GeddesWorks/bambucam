from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TriggerConfig:
    type: str = "gpio"
    gpio_pin: int = 17
    edge: str = "rising"
    debounce_ms: int = 20
    interval_seconds: float = 5.0
    bambuddy_url: str = ""
    bambuddy_printer_id: int = 0
    bambuddy_api_key: str = ""
    poll_interval_seconds: float = 1.0


@dataclass
class CameraConfig:
    type: str = "gphoto2_cli"
    timeout_seconds: int = 30
    retries: int = 3
    retry_delay_seconds: float = 2.0


@dataclass
class CaptureConfig:
    base_dir: str = "./prints"
    frame_format: str = "frame-{:06d}.jpg"


@dataclass
class CompileConfig:
    fps: int = 30
    codec: str = "libx264"
    pixel_format: str = "yuv420p"


@dataclass
class AppwriteConfig:
    endpoint: str = ""
    project_id: str = ""
    api_key: str = ""
    bucket_id: str = ""


@dataclass
class NasConfig:
    dir: str = "/mnt/nas/BambuCam"
    mount_point: str = "/mnt/nas"
    mount_check: bool = True


@dataclass
class UploadConfig:
    backend: str = "appwrite"
    appwrite: AppwriteConfig = field(default_factory=AppwriteConfig)
    nas: NasConfig = field(default_factory=NasConfig)
    retry_attempts: int = 3
    retry_backoff_seconds: list[float] = field(default_factory=lambda: [5.0, 15.0, 45.0])


@dataclass
class CleanupConfig:
    enabled: bool = True
    delete_frames: bool = True
    delete_video: bool = True
    keep_meta: bool = True
    keep_logs: bool = True


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "json"
    file: str = "./logs/bambucam.log"


@dataclass
class PrinterHttpConfig:
    listen_port: int = 8420


@dataclass
class PrinterConfig:
    provider: str = "http"
    http: PrinterHttpConfig = field(default_factory=PrinterHttpConfig)


@dataclass
class BambuCamConfig:
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    compile: CompileConfig = field(default_factory=CompileConfig)
    upload: UploadConfig = field(default_factory=UploadConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    printer: PrinterConfig = field(default_factory=PrinterConfig)


_ENV_PATTERN = re.compile(r"\$\{(\w+)}")


def _substitute_env(value: str) -> str:
    def replacer(match: re.Match) -> str:
        env_var = match.group(1)
        env_value = os.environ.get(env_var)
        if env_value is None:
            raise ValueError(f"Environment variable {env_var} is not set")
        return env_value
    return _ENV_PATTERN.sub(replacer, value)


def _resolve_env_vars(obj: object) -> object:
    if isinstance(obj, str):
        return _substitute_env(obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


_NESTED_TYPES: dict[str, type] = {
    "appwrite": AppwriteConfig,
    "nas": NasConfig,
    "http": PrinterHttpConfig,
}


def _build_dataclass(cls: type, data: dict) -> object:
    if not data:
        return cls()
    kwargs = {}
    for key, value in data.items():
        if key not in cls.__dataclass_fields__:
            continue
        if isinstance(value, dict) and key in _NESTED_TYPES:
            kwargs[key] = _build_dataclass(_NESTED_TYPES[key], value)
        else:
            kwargs[key] = value
    return cls(**kwargs)


def _dict_to_config(data: dict) -> BambuCamConfig:
    config = BambuCamConfig()
    section_map = {
        "trigger": TriggerConfig,
        "camera": CameraConfig,
        "capture": CaptureConfig,
        "compile": CompileConfig,
        "upload": UploadConfig,
        "cleanup": CleanupConfig,
        "logging": LoggingConfig,
        "printer": PrinterConfig,
    }
    for section, cls in section_map.items():
        if section in data:
            setattr(config, section, _build_dataclass(cls, data[section]))
    return config


def load_config(config_path: Path | str) -> BambuCamConfig:
    config_path = Path(config_path)
    if not config_path.exists():
        return BambuCamConfig()
    raw = yaml.safe_load(config_path.read_text())
    if not raw:
        return BambuCamConfig()
    resolved = _resolve_env_vars(raw)
    return _dict_to_config(resolved)
