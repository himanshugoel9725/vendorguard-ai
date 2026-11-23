"""compose: cover, pagination, evidence map, injection placement, variant stability."""

from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.controls.loader import load_controls
from vendorguard.eval.sample_gen.compose import compose
from vendorguard.eval.sample_gen.layout import block_cost
from vendorguard.eval.sample_gen.phrases import load_phrases
from vendorguard.eval.specs import SampleState, load_spec
from vendorguard.utils.keywords import matching_phrases

STEMS = ["brightdock", "nimbara-hr", "nimbara-hr-y2", "quillfield"]


@pytest.fixture
def env(settings_override: Callable[..., Settings], project_root: Path):  # type: ignore[no-untyped-def]
    controls = load_controls(project_root / "config/controls/baseline_v1.yaml")
    bank = load_phrases(project_root / "data/samples/phrases.yaml")

    def spec(stem: str):  # type: ignore[no-untyped-def]
        return load_spec(project_root / f"data/samples/specs/{stem}.yaml")

    return settings_override, controls, bank, spec


@pytest.mark.parametrize("stem", STEMS)
def test_cover_page(env, stem: str) -> None:  # type: ignore[no-untyped-def]
    so, controls, bank, spec = env
    sp = spec(stem)
    page1 = compose(sp, bank, controls, so().samples).pages[0]
    assert (page1[0].kind, page1[0].text) == ("title", "Security & Trust Overview")
    assert (page1[1].kind, page1[1].text) == ("subtitle", sp.vendor_name)
    assert page1[2].text == f"Reporting period: {sp.report_period}."
    texts = " ".join(b.text for b in page1)
    assert ("Key suppliers:" in texts) == bool(sp.subprocessors)
    assert ("Independent reports held:" in texts) == bool(sp.certifications)
    keywords = [k for c in controls.controls for k in c.keywords]
    for block in page1:
        if block.text.startswith("Independent reports held"):
            continue
        assert matching_phrases(block.text, keywords) == [], block.text


@pytest.mark.parametrize("stem", STEMS)
def test_sections_and_evidence(env, stem: str) -> None:  # type: ignore[no-untyped-def]
    so, controls, bank, spec = env
    sp = spec(stem)
    s = so().samples
    composed = compose(sp, bank, controls, s)
    heads = [(i, b.text) for i, p in enumerate(composed.pages, 1) for b in p if b.kind == "heading"]
    assert [h[1] for h in heads] == [
        f"Section {n}: {bank.section_titles[d]}" for n, d in enumerate(controls.domains, 1)
    ]
    assert all(composed.pages[i - 1][0].kind == "heading" and i >= 2 for i, _ in heads)
    ids = list(composed.evidence)
    assert len(ids) == 25 and ids == sorted(ids)
    for cid, entry in composed.evidence.items():
        assert entry.state is sp.controls[cid]
        if entry.state is SampleState.MISSING:
            assert entry.page is None and entry.sentence is None and entry.variant is None
            continue
        assert entry.page is not None and entry.page >= 2
        options = getattr(bank.controls[cid], entry.state.value)
        assert entry.variant is not None and entry.sentence == options[entry.variant]
        assert [b.control_id for b in composed.pages[entry.page - 1]].count(cid) == 1


@pytest.mark.parametrize("lines", [40, 12, 3, 1])
def test_budget_and_headings(env, lines: int) -> None:  # type: ignore[no-untyped-def]
    so, controls, bank, spec = env
    s = so(samples={"lines_per_page": lines}).samples
    composed = compose(spec("nimbara-hr"), bank, controls, s)
    for page in composed.pages[1:]:  # the cover is not paginated
        cost = sum(block_cost(b, s.wrap_chars) for b in page)
        # a page may exceed a tiny budget only as one block, or as a heading with its paragraph
        pair = len(page) == 2 and page[0].kind == "heading"
        assert cost <= s.lines_per_page or len(page) == 1 or pair
        assert page[-1].kind != "heading"
    assert len([b for p in composed.pages for b in p if b.kind == "heading"]) == 8


def test_default_lines_per_page_is_respected(env) -> None:  # type: ignore[no-untyped-def]
    so, controls, bank, spec = env
    s = so().samples
    composed = compose(spec("brightdock"), bank, controls, s)
    assert all(
        sum(block_cost(b, s.wrap_chars) for b in page) <= s.lines_per_page
        for page in composed.pages
    )


def test_injection_only_in_quillfield_after_second_control(env) -> None:  # type: ignore[no-untyped-def]
    so, controls, bank, spec = env
    s = so().samples
    for stem in STEMS:
        composed = compose(spec(stem), bank, controls, s)
        flat = [b for p in composed.pages for b in p]
        inj = [i for i, b in enumerate(flat) if b.kind == "injection"]
        if stem != "quillfield":
            assert inj == []
            continue
        assert len(inj) == 1
        start = max(i for i, b in enumerate(flat[: inj[0]]) if b.kind == "heading")
        assert flat[start].text.endswith(bank.section_titles["DAT"])
        before = [b for b in flat[start : inj[0]] if b.control_id]
        assert len(before) == 2


def test_year2_keeps_variants_for_unchanged_controls(env) -> None:  # type: ignore[no-untyped-def]
    so, controls, bank, spec = env
    s = so().samples
    y1 = compose(spec("nimbara-hr"), bank, controls, s).evidence
    y2 = compose(spec("nimbara-hr-y2"), bank, controls, s).evidence
    same = [c for c in y1 if y1[c].state is y2[c].state]
    assert same
    for cid in same:
        assert (y1[cid].sentence, y1[cid].variant) == (y2[cid].sentence, y2[cid].variant)


def test_compose_is_deterministic(env) -> None:  # type: ignore[no-untyped-def]
    so, controls, bank, spec = env
    s = so().samples
    assert compose(spec("quillfield"), bank, controls, s) == compose(
        spec("quillfield"), bank, controls, s
    )


def test_cover_names_certifications_only_when_tpr02_is_met(env) -> None:  # type: ignore[no-untyped-def]
    """The certification line matches TPR-02 keywords, so it must never contradict the spec."""
    from vendorguard.eval.specs import SampleState

    so, controls, bank, spec = env
    s = so().samples
    base = spec("nimbara-hr")
    assert base.controls["TPR-02"] is SampleState.MET and base.certifications
    cover = compose(base, bank, controls, s).pages[0]
    assert any("Independent reports held" in b.text for b in cover)
    for state in (SampleState.PARTIAL, SampleState.NOT_MET, SampleState.MISSING):
        altered = base.model_copy(update={"controls": {**base.controls, "TPR-02": state}})
        cover = compose(altered, bank, controls, s).pages[0]
        assert not any("Independent reports held" in b.text for b in cover)
        assert not any("SOC 2" in b.text for b in cover)
