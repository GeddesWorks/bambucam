from __future__ import annotations

import logging
import signal
import threading
import time
from pathlib import Path

from bambucam.camera.base import CameraService
from bambucam.compiler.ffmpeg import FfmpegCompiler
from bambucam.config import BambuCamConfig, load_config
from bambucam.logging import log_event, setup_logging
from bambucam.orchestrator import Orchestrator
from bambucam.printer.http import HttpPrinterProvider
from bambucam.upload.base import Uploader

logger = logging.getLogger("bambucam")

DEFAULT_CONFIG_PATHS = [
    Path("config/config.yaml"),
    Path("/etc/bambucam/config.yaml"),
]


def _find_config() -> Path | None:
    for path in DEFAULT_CONFIG_PATHS:
        if path.exists():
            return path
    return None


def _build_camera(config: BambuCamConfig) -> CameraService:
    if config.camera.type == "mock":
        from bambucam.camera.mock import MockCamera
        return MockCamera()
    from bambucam.camera.gphoto2 import GPhoto2Camera
    return GPhoto2Camera(
        timeout=config.camera.timeout_seconds,
        retries=config.camera.retries,
        retry_delay=config.camera.retry_delay_seconds,
    )


def _start_retry_sweep(orchestrator, config) -> None:
    """Retry stranded jobs on a timer so a transient NAS outage self-heals."""
    minutes = config.upload.retry_sweep_minutes
    if not minutes or minutes <= 0:
        return

    import threading

    def sweep() -> None:
        while True:
            time.sleep(minutes * 60)
            try:
                orchestrator.retry_stranded_jobs()
            except Exception as e:  # a sweep must never kill the daemon
                logger.warning("Retry sweep failed: %s", e,
                               extra={"event": "RETRY_SWEEP_FAILED"})

    threading.Thread(target=sweep, daemon=True, name="retry-sweep").start()
    logger.info("Retry sweep every %.0f min", minutes,
                extra={"event": "RETRY_SWEEP_STARTED"})


def _build_uploader(config: BambuCamConfig) -> Uploader:
    if config.upload.backend == "none":
        from bambucam.upload.none import NoOpUploader
        return NoOpUploader()
    if config.upload.backend == "nas":
        from bambucam.upload.nas import NasUploader
        return NasUploader(
            base_dir=config.upload.nas.dir,
            mount_point=config.upload.nas.mount_point,
            mount_check=config.upload.nas.mount_check,
        )
    from bambucam.upload.appwrite import AppwriteUploader
    aw = config.upload.appwrite
    return AppwriteUploader(
        endpoint=aw.endpoint,
        project_id=aw.project_id,
        api_key=aw.api_key,
        bucket_id=aw.bucket_id,
    )


def _build_compiler(config: BambuCamConfig) -> FfmpegCompiler:
    return FfmpegCompiler(
        codec=config.compile.codec,
        pixel_format=config.compile.pixel_format,
        scale_width=config.compile.scale_width,
        preset=config.compile.preset,
        threads=config.compile.threads,
        rc_lookahead=config.compile.rc_lookahead,
        crf=config.compile.crf,
    )


def main() -> None:
    config_path = _find_config()
    config = load_config(config_path) if config_path else BambuCamConfig()

    logger = setup_logging(
        level=config.logging.level,
        log_file=config.logging.file,
        fmt=config.logging.format,
    )
    log_event(logger, "DAEMON_STARTED", "BambuCam daemon starting")

    camera = _build_camera(config)
    compiler = _build_compiler(config)
    uploader = _build_uploader(config)

    orchestrator = Orchestrator(config, camera, compiler, uploader)
    orchestrator.recover_jobs()
    _start_retry_sweep(orchestrator, config)

    printer = HttpPrinterProvider(port=config.printer.http.listen_port)
    printer.start(callback=orchestrator.on_print_event)

    # Trigger setup — GPIO only available on Pi
    trigger = None
    if config.trigger.type == "mock":
        from bambucam.trigger.mock import MockTriggerProvider
        trigger = MockTriggerProvider(interval_seconds=config.trigger.interval_seconds)
        trigger.start(callback=orchestrator.on_trigger)
    elif config.trigger.type == "bambuddy":
        from bambucam.trigger.bambuddy import BambuddyLayerTrigger
        trigger = BambuddyLayerTrigger(
            base_url=config.trigger.bambuddy_url,
            printer_id=config.trigger.bambuddy_printer_id,
            api_key=config.trigger.bambuddy_api_key,
            poll_interval_seconds=config.trigger.poll_interval_seconds,
        )
        trigger.start(callback=orchestrator.on_trigger)
    elif config.trigger.type == "gpio":
        try:
            from bambucam.trigger.gpio import GpioTriggerProvider
            trigger = GpioTriggerProvider(
                pin=config.trigger.gpio_pin,
                edge=config.trigger.edge,
                debounce_ms=config.trigger.debounce_ms,
            )
            trigger.start(callback=orchestrator.on_trigger)
        except RuntimeError as e:
            log_event(logger, "TRIGGER_UNAVAILABLE",
                      f"GPIO trigger not available: {e}", level="WARNING")

    shutdown = threading.Event()

    def handle_signal(signum: int, frame) -> None:
        log_event(logger, "DAEMON_STOPPING", "Shutdown signal received")
        shutdown.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log_event(logger, "DAEMON_READY", "BambuCam daemon ready and waiting")
    shutdown.wait()

    if trigger:
        trigger.stop()
    printer.stop()
    log_event(logger, "DAEMON_STOPPED", "BambuCam daemon stopped")


if __name__ == "__main__":
    main()
