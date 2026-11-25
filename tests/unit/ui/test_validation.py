"""The UI's input patterns must equal the server's, or the UI would accept what the API refuses."""

from vendorguard.api.routes.assessments import ControlId
from vendorguard.pipeline.run_index import RUN_ID_PATTERN, VENDOR_ID_PATTERN
from vendorguard.ui import validation


def test_patterns_equal_the_servers() -> None:
    assert validation.VENDOR_ID_PATTERN.pattern == VENDOR_ID_PATTERN.pattern
    assert validation.RUN_ID_PATTERN.pattern == RUN_ID_PATTERN.pattern
    server_control = ControlId.__metadata__[0].metadata[0].pattern  # type: ignore[attr-defined]
    assert validation.CONTROL_ID_PATTERN.pattern == server_control


def test_the_patterns_refuse_what_they_should() -> None:
    assert validation.VENDOR_ID_PATTERN.match("nimbara-hr")
    for bad in ("", "../x", "a b", "-lead", "x" * 65):
        assert not validation.VENDOR_ID_PATTERN.match(bad)
    assert not validation.RUN_ID_PATTERN.match("../etc") and validation.CONTROL_ID_PATTERN.match(
        "IAM-02"
    )
