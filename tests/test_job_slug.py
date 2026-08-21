from bambucam.models import slugify_job_name


def test_percent_is_removed():
    """gphoto2 and ffmpeg both parse '%' in a path as a format specifier."""
    slug = slugify_job_name("0.2mm layer, 2 walls, 15% infill")
    assert "%" not in slug
    assert slug == "0.2mm-layer-2-walls-15-infill"


def test_spaces_and_commas_collapse():
    assert slugify_job_name("a,  b") == "a-b"


def test_keeps_dots_and_dashes():
    assert slugify_job_name("benchy-v2.1") == "benchy-v2.1"


def test_empty_or_junk_name_still_yields_a_usable_id():
    assert slugify_job_name("") == "print"
    assert slugify_job_name("%%%") == "print"


def test_is_length_bounded():
    assert len(slugify_job_name("x" * 500)) <= 60


def test_no_leading_or_trailing_separators():
    s = slugify_job_name("  %weird%  ")
    assert not s.startswith(("-", "."))
    assert not s.endswith(("-", "."))
