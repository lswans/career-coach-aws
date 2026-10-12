import pytest

from coach.ingest import Document
from coach.validation import IntakeError, validate_intake

DOCS = [Document(name="resume.md", kind="file", text="Python developer. " * 10)]


def test_goals_need_200_characters(settings):
    with pytest.raises(IntakeError) as err:
        validate_intake("a" * 199, DOCS, settings)
    assert set(err.value.fields) == {"goals"}
    assert "199" in err.value.fields["goals"]


def test_exactly_200_characters_passes_and_is_trimmed(settings):
    assert validate_intake("   " + "a" * 200 + "\n", DOCS, settings) == "a" * 200


def test_whitespace_padding_does_not_count(settings):
    with pytest.raises(IntakeError):
        validate_intake(" " * 300 + "too short", DOCS, settings)


def test_documents_are_required(settings):
    with pytest.raises(IntakeError) as err:
        validate_intake("a" * 250, [], settings)
    assert set(err.value.fields) == {"documents"}


def test_every_problem_is_reported_at_once(settings):
    with pytest.raises(IntakeError) as err:
        validate_intake("short", [], settings, file_errors=["photo.png: unsupported file type."])
    assert set(err.value.fields) == {"documents", "goals", "files"}


def test_bad_file_blocks_synthesis_even_with_good_documents(settings):
    with pytest.raises(IntakeError) as err:
        validate_intake("a" * 250, DOCS, settings, file_errors=["scan.pdf: no readable text."])
    assert set(err.value.fields) == {"files"}
