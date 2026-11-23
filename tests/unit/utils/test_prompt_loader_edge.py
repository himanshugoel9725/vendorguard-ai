"""Prompt loader edge cases: Jinja features, headings, front-matter variants, sizes, unicode."""

from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.config_models.core import PromptsSettings
from vendorguard.errors import ConfigError
from vendorguard.utils.prompt_loader import PromptLoader

Make = Callable[..., PromptLoader]


def doc(body: str, name: str = "mapper", version: str = "v1", extra: str = "") -> str:
    return f"---\nid: {name}\nversion: {version}\noutput_model: X\n{extra}---\n{body}"


@pytest.fixture
def make(settings_override: Callable[..., Settings], tmp_path: Path) -> Make:
    def build(text: str | bytes, name: str = "mapper", version: str = "v1") -> PromptLoader:
        data = text if isinstance(text, bytes) else text.encode("utf-8")
        (tmp_path / f"{name}.{version}.md").write_bytes(data)
        return PromptLoader(tmp_path, settings_override(prompts={name: version}).prompts)

    return build


def user(make: Make, body: str, **kw: object) -> str:
    return make(doc(f"## user\n{body}\n")).render("mapper", **kw).messages[0].content


def test_for_loop_with_loop_index(make: Make) -> None:
    assert (
        user(make, "{% for x in xs %}{{ loop.index }}={{ x }};{% endfor %}", xs="ab") == "1=a;2=b;"
    )


def test_if_else_and_filters(make: Make) -> None:
    body = "{% if n > 1 %}many{% else %}one{% endif %} {{ xs|join(',') }} {{ s|upper }} "
    body += "{{ xs|length }} {{ missing|default('d') if false else 'ok' }}"
    assert user(make, body, n=2, xs=["a", "b"], s="hi") == "many a,b HI 2 ok"
    assert user(make, "{{ v|default('fallback') }}", v="") == ""


def test_set_macro_and_whitespace_control(make: Make) -> None:
    body = "{% set a = 3 %}{% macro dbl(x) %}{{ x * 2 }}{% endmacro %}{{ dbl(a) }}\n{{- '!' }}"
    assert user(make, body) == "6!"


def test_macro_defined_in_one_section_is_not_visible_in_another(make: Make) -> None:
    text = doc("## system\n{% macro m() %}x{% endmacro %}{{ m() }}\n## user\n{{ m() }}\n")
    with pytest.raises(ConfigError, match="'m' is undefined|m"):
        make(text).render("mapper")


def test_large_variable_and_large_loop(make: Make) -> None:
    big = "é" * 1_000_000
    assert user(make, "{{ v }}", v=big) == big
    out = user(make, "{% for i in range(10000) %}{{ i }},{% endfor %}")
    assert out.startswith("0,1,2,") and out.endswith("9999,")


def test_unicode_template_and_variable(make: Make) -> None:
    assert user(make, "Привет {{ n }} 你好 🔐", n="Zoë") == "Привет Zoë 你好 🔐"


def test_utf8_bom_at_start_is_reported_as_missing_front_matter(make: Make) -> None:
    raw = b"\xef\xbb\xbf" + doc("## user\nhi\n").encode()
    with pytest.raises(ConfigError, match="missing front-matter"):
        make(raw).load("mapper")


def test_crlf_files_render_with_lf(make: Make) -> None:
    text = (
        doc("## system\r\nA\r\nB\r\n## user\r\nC\r\n").replace("\n", "\r\n").replace("\r\r", "\r")
    )
    out = make(text).render("mapper")
    assert [m.content for m in out.messages] == ["A\nB", "C"]


@pytest.mark.parametrize(
    "heading", ["##system", "##  user", "## User", "## user trailing", "# user"]
)
def test_non_exact_headings_are_not_headings(make: Make, heading: str) -> None:
    out = make(doc(f"## user\nfirst\n{heading}\nsecond\n")).render("mapper")
    assert len(out.messages) == 1
    assert f"{heading}\nsecond" in out.messages[0].content


@pytest.mark.parametrize("heading", ["##system", "##  user", "## System", "## user trailing"])
def test_a_non_exact_heading_first_means_no_section(make: Make, heading: str) -> None:
    with pytest.raises(ConfigError, match="needs at least one"):
        make(doc(f"{heading}\nhello\n")).load("mapper")


def test_text_before_first_heading_is_an_error(make: Make) -> None:
    with pytest.raises(ConfigError, match="text before the first section heading"):
        make(doc("intro\n## user\nhi\n")).load("mapper")


def test_heading_with_trailing_spaces_and_tabs_is_accepted(make: Make) -> None:
    out = make(doc("## system \t \nS\n## user\t\nU\n")).render("mapper")
    assert [m.role for m in out.messages] == ["system", "user"]


def test_three_dashes_inside_a_section_body_stay_text(make: Make) -> None:
    out = make(doc("## user\nabove\n---\nbelow\n")).render("mapper")
    assert out.messages[0].content == "above\n---\nbelow"


def test_extra_front_matter_keys_are_rejected_by_the_strict_contract(make: Make) -> None:
    with pytest.raises(ConfigError, match="invalid front-matter"):
        make(doc("## user\nx\n", extra="owner: me\n")).load("mapper")


def test_duplicate_front_matter_keys_are_accepted_last_one_wins(make: Make) -> None:
    text = "---\nid: mapper\nversion: v9\nversion: v1\noutput_model: X\n---\n## user\nx\n"
    assert make(text).load("mapper").meta.version == "v1"


@pytest.mark.parametrize("front", ["- a\n- b", "", "just a string"])
def test_bad_front_matter_shapes(make: Make, front: str) -> None:
    with pytest.raises(ConfigError, match="front-matter"):
        make(f"---\n{front}\n---\n## user\nhi\n").load("mapper")


def test_second_front_matter_block_is_plain_body_text_before_a_heading(make: Make) -> None:
    with pytest.raises(ConfigError, match="text before the first section heading"):
        make(doc("---\nid: x\n---\n## user\nhi\n")).load("mapper")


@pytest.mark.parametrize("version", ["v1", "v10", "v100"])
def test_versions_with_different_formats(
    settings_override: Callable[..., Settings], tmp_path: Path, version: str
) -> None:
    (tmp_path / f"judge.{version}.md").write_text(doc("## user\nj\n", "judge", version))
    loader = PromptLoader(tmp_path, settings_override(prompts={"judge": version}).prompts)
    assert loader.render("judge").messages[0].content == "j"


def test_every_prompt_field_of_settings_loads(
    settings_override: Callable[..., Settings], tmp_path: Path
) -> None:
    prompts = settings_override().prompts
    names = list(PromptsSettings.model_fields)
    assert {"intake", "mapper", "reviewer", "judge", "reporter", "ask"} <= set(names)
    for name in names:
        version = getattr(prompts, name)
        (tmp_path / f"{name}.{version}.md").write_text(doc(f"## user\n{name}\n", name, version))
    loader = PromptLoader(tmp_path, prompts)
    for name in names:
        assert loader.render(name).messages[0].content == name
