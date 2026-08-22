import urllib.error

from bambucam.printer.bambuddy_names import fetch_print_name
from bambucam.upload.nas import NasUploader

ARCHIVES = [
    {"filename": "0.2mm layer, 2 walls, 7% infill.3mf",
     "print_name": "Fidget Slider - relaxation in your hand!"},
    {"filename": "something else.3mf", "print_name": "Other Thing"},
]


def fetcher(payload):
    def _f(url, api_key, timeout):
        if isinstance(payload, Exception):
            raise payload
        return payload
    return _f


def test_finds_the_model_name_for_a_matching_job():
    name = fetch_print_name("http://b:8000", "k", "0.2mm layer, 2 walls, 7% infill",
                            fetch=fetcher(ARCHIVES))
    assert name == "Fidget Slider - relaxation in your hand!"


def test_returns_none_when_no_archive_matches():
    assert fetch_print_name("http://b:8000", "k", "unknown job",
                            fetch=fetcher(ARCHIVES)) is None


def test_handles_paginated_envelope():
    assert fetch_print_name("http://b:8000", "k", "something else",
                            fetch=fetcher({"items": ARCHIVES})) == "Other Thing"


def test_network_failure_returns_none_rather_than_raising():
    """A naming nicety must never break an upload."""
    assert fetch_print_name("http://b:8000", "k", "x",
                            fetch=fetcher(urllib.error.URLError("down"))) is None


def test_missing_url_short_circuits():
    assert fetch_print_name("", "k", "job") is None


def test_blank_print_name_is_not_used():
    recs = [{"filename": "job.3mf", "print_name": "   "}]
    assert fetch_print_name("http://b:8000", "k", "job", fetch=fetcher(recs)) is None


# --- filename construction ---

def _upload(tmp_path, metadata):
    video = tmp_path / "output.mp4"
    video.write_bytes(b"x" * 50)
    up = NasUploader(base_dir=str(tmp_path / "BambuCam"), mount_check=False)
    return up.upload(video, metadata)


def test_video_is_named_after_the_model_when_known(tmp_path):
    r = _upload(tmp_path, {"job_id": "0.2mm-layer-2-walls-7-infill-1787434493",
                           "job_name": "0.2mm layer, 2 walls, 7% infill",
                           "print_name": "Fidget Slider - relaxation in your hand!"})
    assert r.success
    from pathlib import Path
    name = Path(r.file_id).name
    assert "Fidget-Slider" in name
    assert "0.2mm-layer" not in name
    assert "!" not in name and " " not in name


def test_falls_back_to_the_job_slug_without_a_print_name(tmp_path):
    from pathlib import Path
    r = _upload(tmp_path, {"job_id": "benchy-1787434493", "job_name": "benchy",
                           "print_name": None})
    assert Path(r.file_id).name.endswith("_benchy.mp4")


def test_blank_print_name_falls_back_too(tmp_path):
    from pathlib import Path
    r = _upload(tmp_path, {"job_id": "benchy-1787434493", "job_name": "benchy",
                           "print_name": "  "})
    assert Path(r.file_id).name.endswith("_benchy.mp4")


def test_matches_when_the_job_name_arrives_already_slugified():
    """Punctuation survives differently on either side: "0.2mm layer, 2 walls,
    15% infill" and "0.2mm-layer-2-walls-15-infill" are the same print."""
    recs = [{"filename": "0.2mm layer, 2 walls, 15% infill.3mf",
             "print_name": "Ratchet Strap Organizer"}]
    assert fetch_print_name("http://b:8000", "k",
                            "0.2mm-layer-2-walls-15-infill",
                            fetch=fetcher(recs)) == "Ratchet Strap Organizer"


def test_slug_matching_does_not_collapse_distinct_prints():
    recs = [{"filename": "gadget v1.3mf", "print_name": "Gadget One"},
            {"filename": "gadget v2.3mf", "print_name": "Gadget Two"}]
    assert fetch_print_name("http://b:8000", "k", "gadget-v2",
                            fetch=fetcher(recs)) == "Gadget Two"
