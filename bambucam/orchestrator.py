from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from bambucam.camera.base import CameraService
from bambucam.compiler.base import Compiler
from bambucam.config import BambuCamConfig
from bambucam.logging import log_event
from bambucam.models import JobDirectory, JobMeta, PrintJob, UploadResult
from bambucam.state_machine import State, StateMachine, persist_state
from bambucam.upload.base import Uploader

logger = logging.getLogger("bambucam")


class Orchestrator:
    def __init__(self, config: BambuCamConfig, camera: CameraService,
                 compiler: Compiler, uploader: Uploader):
        self._config = config
        self._camera = camera
        self._compiler = compiler
        self._uploader = uploader
        self._base_dir = Path(config.capture.base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

        self._sm = StateMachine(on_transition=self._on_transition)
        self._job_dir: JobDirectory | None = None
        self._meta: JobMeta | None = None
        self._frame_count = 0
        self._capture_lock = threading.Lock()
        self._pipeline_thread: threading.Thread | None = None

    @property
    def state(self) -> State:
        return self._sm.state

    @property
    def current_job(self) -> JobMeta | None:
        return self._meta

    def on_print_event(self, event: str, job: PrintJob | None) -> None:
        if event == "print_started" and job:
            self._start_job(job)
        elif event == "print_completed":
            self._complete_job(cancelled=False, failed=False)
        elif event == "print_cancelled":
            self._complete_job(cancelled=True, failed=False)
        elif event == "print_failed":
            self._complete_job(cancelled=False, failed=True)

    def on_trigger(self) -> None:
        if not self._sm.is_capturing:
            return
        threading.Thread(target=self._capture_frame, daemon=True).start()

    def _unfinished_jobs(self):
        """(job_path, meta) for every job that has not reached a good end."""
        if not self._base_dir.exists():
            return
        for job_path in sorted(self._base_dir.iterdir()):
            meta_path = job_path / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = JobMeta.from_dict(json.loads(meta_path.read_text()))
            except (json.JSONDecodeError, KeyError):
                logger.warning("Corrupt meta.json in %s, skipping", job_path,
                               extra={"event": "RECOVERY_SKIPPED"})
                continue
            if meta.state == "IDLE" or meta.upload_status == "verified":
                continue
            yield job_path, meta

    def _resume_job(self, job_path: Path, meta: JobMeta, event: str) -> None:
        log_event(logger, event,
                  f"Resuming job {meta.job_id} from state {meta.state}",
                  job_id=meta.job_id, state=meta.state)

        self._job_dir = JobDirectory(
            root=job_path,
            frames_dir=job_path / "frames",
            meta_path=job_path / "meta.json",
            events_log_path=job_path / "events.log",
            video_path=job_path / "output.mp4",
        )
        self._meta = meta
        self._frame_count = self._job_dir.frame_count()
        state = State(meta.state)

        if state == State.CAPTURING:
            self._meta.state = State.COMPILING.value
            self._sm.force_state(State.COMPILING)
            self._run_pipeline_from(State.COMPILING)
        elif state in (State.COMPILING, State.UPLOADING,
                       State.VERIFYING, State.CLEANUP):
            self._sm.force_state(state)
            self._run_pipeline_from(state)
        elif state.name.startswith("ERROR_"):
            recovery_map = {
                State.ERROR_COMPILE: State.COMPILING,
                State.ERROR_UPLOAD: State.UPLOADING,
                State.ERROR_CAMERA: State.COMPILING,
                State.ERROR_STORAGE: State.COMPILING,
            }
            resume = recovery_map.get(state, State.COMPILING)
            self._sm.force_state(resume)
            self._run_pipeline_from(resume)

        # _run_pipeline_from runs in a thread, and every job shares
        # self._meta / self._job_dir. Starting the next job before this one
        # finishes overwrites that state mid-flight: the finishing job's
        # cleanup sets _meta to None and the next thread dies on
        # 'NoneType' object has no attribute 'job_id', leaving the state
        # machine wedged so later prints are refused as "not idle".
        self._await_pipeline()

    def recover_jobs(self) -> None:
        for job_path, meta in self._unfinished_jobs():
            self._resume_job(job_path, meta, "RECOVERY_STARTED")

    def retry_stranded_jobs(self) -> int:
        """Retry jobs left in an error state, e.g. after the NAS went away.

        Without this a finished video sits in ERROR_UPLOAD until someone
        restarts the daemon — which is how a print stayed unarchived for a day
        after the share silently unmounted.

        Only runs while idle: resuming a job rebinds the shared _meta and
        _job_dir, which would corrupt a capture in progress.
        """
        if not self._sm.is_idle:
            return 0

        retried = 0
        for job_path, meta in self._unfinished_jobs():
            if not meta.state.startswith("ERROR_"):
                continue
            if not self._sm.is_idle:
                break  # a print started while we were working
            self._resume_job(job_path, meta, "RETRY_STARTED")
            retried += 1
        if retried:
            log_event(logger, "RETRY_SWEEP_DONE",
                      f"Retried {retried} stranded job(s)")
        return retried

    def _await_pipeline(self, timeout: float = 3600.0) -> None:
        """Block until the running pipeline thread finishes, if any."""
        thread = self._pipeline_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning(
                    "Pipeline still running after %ss; continuing", timeout,
                    extra={"event": "PIPELINE_SLOW"})

    def _start_job(self, job: PrintJob) -> None:
        if not self._sm.is_idle:
            logger.warning("Ignoring print_started — not idle (state=%s)",
                           self._sm.state.value,
                           extra={"event": "PRINT_IGNORED"})
            return

        self._sm.transition_to(State.PRINT_STARTING)

        self._job_dir = JobDirectory.create(self._base_dir, job.job_id)
        self._meta = JobMeta.from_print_job(
            job, fps=self._config.compile.fps,
        )
        self._frame_count = 0
        self._save_meta()

        log_event(logger, "PRINT_STARTED",
                  f"Starting job: {job.job_name} ({job.job_id})",
                  job_id=job.job_id)

        if self._camera.is_ready():
            log_event(logger, "CAMERA_READY", "Camera is ready",
                      job_id=job.job_id)
        else:
            log_event(logger, "CAMERA_ERROR", "Camera not ready at job start",
                      level="WARNING", job_id=job.job_id)

        self._sm.transition_to(State.CAPTURING)
        self._save_meta()

    def _capture_frame(self) -> None:
        with self._capture_lock:
            if not self._sm.is_capturing or self._job_dir is None:
                return

            self._frame_count += 1
            frame_num = self._frame_count
            dest = self._job_dir.next_frame_path(frame_num)

            try:
                start = time.monotonic()
                self._camera.capture_and_download(dest)
                duration = time.monotonic() - start
                self._meta.frame_count = frame_num
                self._save_meta()
                log_event(logger, "FRAME_CAPTURED",
                          f"Captured {dest.name} in {duration:.1f}s",
                          job_id=self._meta.job_id, frame=frame_num,
                          duration=round(duration, 1))
            except Exception as e:
                self._frame_count -= 1
                log_event(logger, "FRAME_FAILED",
                          f"Capture failed: {e}",
                          level="ERROR", job_id=self._meta.job_id,
                          frame=frame_num)

    def _complete_job(self, cancelled: bool, failed: bool) -> None:
        if self._meta is None:
            return

        if cancelled:
            self._meta.cancelled = True
            log_event(logger, "PRINT_CANCELLED", "Print was cancelled",
                      job_id=self._meta.job_id)
        elif failed:
            self._meta.failed = True
            log_event(logger, "PRINT_FAILED", "Print failed",
                      job_id=self._meta.job_id)
        else:
            log_event(logger, "PRINT_COMPLETED", "Print completed",
                      job_id=self._meta.job_id)

        self._meta.completed_at = datetime.now(timezone.utc).isoformat()
        self._save_meta()
        self._run_pipeline_from(State.COMPILING)

    def _run_pipeline_from(self, start_state: State) -> None:
        def run() -> None:
            try:
                if start_state == State.COMPILING:
                    self._do_compile()
                if self._sm.state == State.UPLOADING or start_state == State.UPLOADING:
                    self._do_upload()
                if self._sm.state == State.VERIFYING or start_state == State.VERIFYING:
                    self._do_verify()
                if self._sm.state == State.CLEANUP or start_state == State.CLEANUP:
                    self._do_cleanup()
            except Exception as e:
                logger.error("Pipeline error: %s", e,
                             extra={"event": "PIPELINE_ERROR"})

        self._pipeline_thread = threading.Thread(target=run, daemon=True)
        self._pipeline_thread.start()

    def _do_compile(self) -> None:
        if self._sm.state == State.CAPTURING:
            self._sm.transition_to(State.COMPILING)
        elif self._sm.state != State.COMPILING:
            self._sm.force_state(State.COMPILING)
        self._save_meta()

        if self._frame_count < 2:
            log_event(logger, "COMPILE_SKIPPED",
                      f"Only {self._frame_count} frame(s), skipping to cleanup",
                      job_id=self._meta.job_id)
            self._sm.transition_to(State.UPLOADING)
            self._sm.transition_to(State.VERIFYING)
            self._sm.transition_to(State.CLEANUP)
            self._do_cleanup()
            return

        fps = self._config.compile.fps_for(self._frame_count)
        self._meta.video_fps = fps
        success = self._compiler.compile(
            self._job_dir.frames_dir,
            self._job_dir.video_path,
            fps=fps,
        )

        if success:
            self._meta.video_compiled = True
            self._sm.transition_to(State.UPLOADING)
            self._save_meta()
        else:
            self._sm.transition_to(State.ERROR_COMPILE)
            self._save_meta()

    def _lookup_print_name(self) -> str | None:
        """The model's real name, if Bambuddy knows it. Best effort only."""
        cfg = getattr(self._config, "bambuddy", None)
        if not cfg or not cfg.use_print_name or not cfg.url:
            return None
        try:
            from datetime import datetime

            from bambucam.printer.bambuddy_names import fetch_print_name
            started = None
            if self._meta.started_at:
                try:
                    started = datetime.fromisoformat(self._meta.started_at)
                except ValueError:
                    started = None
            return fetch_print_name(cfg.url, cfg.api_key, self._meta.job_name,
                                    started_at=started)
        except Exception as e:  # naming must never break an upload
            logger.warning("Print name lookup failed: %s", e,
                           extra={"event": "PRINT_NAME_LOOKUP_FAILED"})
            return None

    def _do_upload(self) -> None:
        if not self._job_dir.video_path.exists():
            log_event(logger, "UPLOAD_SKIPPED", "No video file to upload",
                      job_id=self._meta.job_id)
            self._sm.force_state(State.CLEANUP)
            self._do_cleanup()
            return

        backoff = self._config.upload.retry_backoff_seconds
        attempts = self._config.upload.retry_attempts

        for attempt in range(1, attempts + 1):
            result = self._uploader.upload(
                self._job_dir.video_path,
                metadata={"job_id": self._meta.job_id,
                           "job_name": self._meta.job_name,
                           "print_name": self._lookup_print_name(),
                           "frame_count": self._meta.frame_count},
            )
            if result.success:
                self._meta.upload_file_id = result.file_id
                self._meta.upload_status = "uploaded"
                self._sm.transition_to(State.VERIFYING)
                self._save_meta()
                return

            if attempt < attempts:
                delay = backoff[attempt - 1] if attempt - 1 < len(backoff) else backoff[-1]
                log_event(logger, "UPLOAD_RETRY",
                          f"Retry {attempt}/{attempts} in {delay}s",
                          job_id=self._meta.job_id)
                time.sleep(delay)

        self._meta.upload_status = "failed"
        self._sm.transition_to(State.ERROR_UPLOAD)
        self._save_meta()

    def _do_verify(self) -> None:
        if not self._meta.upload_file_id:
            # Reachable after a crash between a successful upload and the
            # metadata write. Cleaning up here would delete the frames and the
            # video while nothing was ever archived. ERROR_UPLOAD preserves
            # them and recovery retries the upload on the next start.
            log_event(logger, "VERIFY_FAILED",
                      "No upload id to verify — retrying upload instead of "
                      "cleaning up",
                      level="ERROR", job_id=self._meta.job_id)
            self._meta.upload_status = "failed"
            self._sm.transition_to(State.ERROR_UPLOAD)
            self._save_meta()
            return

        if self._uploader.verify(self._meta.upload_file_id):
            self._meta.upload_status = "verified"
            log_event(logger, "VERIFY_SUCCESS", "Upload verified",
                      job_id=self._meta.job_id,
                      file_id=self._meta.upload_file_id)
            self._sm.transition_to(State.CLEANUP)
            self._save_meta()
        else:
            log_event(logger, "VERIFY_FAILED", "Upload verification failed",
                      level="ERROR", job_id=self._meta.job_id)
            self._sm.transition_to(State.ERROR_UPLOAD)
            self._save_meta()

    def _do_cleanup(self) -> None:
        if self._sm.state != State.CLEANUP:
            self._sm.force_state(State.CLEANUP)

        cfg = self._config.cleanup
        if not cfg.enabled:
            log_event(logger, "CLEANUP_SKIPPED", "Cleanup disabled",
                      job_id=self._meta.job_id)
            self._sm.transition_to(State.IDLE)
            self._save_meta()
            self._reset()
            return

        if cfg.delete_frames and self._job_dir.frames_dir.exists():
            for frame in self._job_dir.frames_dir.glob("frame-*.jpg"):
                frame.unlink()
            try:
                self._job_dir.frames_dir.rmdir()
            except OSError:
                pass

        if cfg.delete_video and self._job_dir.video_path.exists():
            self._job_dir.video_path.unlink()

        log_event(logger, "CLEANUP_COMPLETED", "Local files cleaned up",
                  job_id=self._meta.job_id)

        self._meta.state = State.IDLE.value
        self._save_meta()
        self._sm.transition_to(State.IDLE)
        self._reset()

    def _save_meta(self) -> None:
        if self._meta and self._job_dir:
            self._meta.state = self._sm.state.value
            persist_state(self._job_dir.meta_path, self._sm.state,
                          self._meta.to_dict())

    def _reset(self) -> None:
        self._job_dir = None
        self._meta = None
        self._frame_count = 0

    def _on_transition(self, old: State, new: State) -> None:
        log_event(logger, "STATE_CHANGED",
                  f"{old.value} → {new.value}",
                  old_state=old.value, new_state=new.value,
                  job_id=self._meta.job_id if self._meta else None)
