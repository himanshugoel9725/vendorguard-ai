"""Prompt loader: files, front-matter, sections, strict rendering, hashing."""

from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.errors import ConfigError
from vendorguard.models.llm import ChatMessage
from vendorguard.utils.hashing import sha256_text
from vendorguard.utils.prompt_loader import PromptLoader

MAPPER = """---
id: mapper
version: v1
output_model: DraftFinding
---
## system
You are a meticulous assessor.
Quote at most {{ max_quote_chars }} characters.

## user
Control {{ control.id }}: {{ control.title }}

{% for c in chunks %}<document chunk_id="{{ c.chunk_id }}" page="{{ c.page }}">
{{ c.text }}
</document>
{% endfor %}
"""


class Obj:
    def __init__(self, **kw: object) -> None:
        self.__dict__.update(kw)


@pytest.fixture
def make(settings_override: Callable[..., Settings], tmp_path: Path) -> Callable[..., PromptLoader]:
    def build(files: dict[str, str] | None = None, **prompts: str) -> PromptLoader:
        for name, text in (files if files is not None else {"mapper.v1.md": MAPPER}).items():
            (tmp_path / name).write_text(text, encoding="utf-8")
        return PromptLoader(
            tmp_path, settings_override(prompts={"mapper": "v1", **prompts}).prompts
        )

    return build


VARS = {
    "max_quote_chars": 400,
    "control": Obj(id="IAM-02", title="Multi-factor authentication"),
    "chunks": [
        Obj(chunk_id="a:p001:c000", page=1, text="MFA is enforced."),
        Obj(chunk_id="a:p002:c000", page=2, text="B"),
    ],
}


def test_rendering_gives_system_and_user_messages_with_the_variables(
    make: Callable[..., PromptLoader],
) -> None:
    out = make().render("mapper", **VARS)
    assert [m.role for m in out.messages] == ["system", "user"]
    assert out.messages[0].content == (
        "You are a meticulous assessor.\nQuote at most 400 characters."
    )
    user = out.messages[1].content
    assert user.startswith("Control IAM-02: Multi-factor authentication\n\n")
    assert '<document chunk_id="a:p001:c000" page="1">\nMFA is enforced.\n</document>' in user
    assert user.endswith("B\n</document>")  # blocks are trimmed; no stray blank lines from the loop


def test_a_missing_variable_raises_and_names_it(make: Callable[..., PromptLoader]) -> None:
    """Task 4.7 done-when."""
    loader = make()
    with pytest.raises(ConfigError, match=r"prompt 'mapper' v1: 'max_quote_chars' is undefined"):
        loader.render("mapper", **{k: v for k, v in VARS.items() if k != "max_quote_chars"})
    with pytest.raises(ConfigError, match="'control' is undefined"):
        loader.render("mapper", max_quote_chars=1, chunks=[])


def test_a_missing_attribute_is_an_error_too(make: Callable[..., PromptLoader]) -> None:
    with pytest.raises(ConfigError, match="has no attribute"):
        make().render("mapper", **{**VARS, "control": Obj(id="IAM-02")})


def test_extra_variables_are_ignored(make: Callable[..., PromptLoader]) -> None:
    assert make().render("mapper", **VARS, unused="x").messages


def test_variable_contents_are_never_interpreted_as_template_code(
    make: Callable[..., PromptLoader],
) -> None:
    """Untrusted document text may contain Jinja syntax; it must come out verbatim."""
    hostile = "{{ 7 * 7 }} {% if True %}x{% endif %} {{ ''.__class__ }}"
    out = make().render("mapper", **{**VARS, "chunks": [Obj(chunk_id="c", page=1, text=hostile)]})
    assert hostile in out.messages[1].content and "49" not in out.messages[1].content


def test_html_like_text_is_not_escaped(make: Callable[..., PromptLoader]) -> None:
    out = make().render(
        "mapper", **{**VARS, "chunks": [Obj(chunk_id="c", page=1, text="a < b & <tag>")]}
    )
    assert "a < b & <tag>" in out.messages[1].content


def test_the_template_can_not_reach_dangerous_attributes(make: Callable[..., PromptLoader]) -> None:
    evil = MAPPER.replace("{{ control.id }}", "{{ control.__class__.__mro__ }}")
    with pytest.raises(ConfigError):
        make({"mapper.v1.md": evil}).render("mapper", **VARS)


def test_the_hash_is_of_the_template_file_and_independent_of_the_variables(
    make: Callable[..., PromptLoader],
) -> None:
    loader = make()
    one = loader.render("mapper", **VARS)
    two = loader.render("mapper", **{**VARS, "max_quote_chars": 5})
    assert (
        one.prompt_hash
        == two.prompt_hash
        == sha256_text(MAPPER)
        == loader.load("mapper").prompt_hash
    )


def test_crlf_files_hash_like_lf_files(
    settings_override: Callable[..., Settings], tmp_path: Path
) -> None:
    (tmp_path / "mapper.v1.md").write_bytes(MAPPER.replace("\n", "\r\n").encode())
    loader = PromptLoader(tmp_path, settings_override(prompts={"mapper": "v1"}).prompts)
    assert loader.load("mapper").prompt_hash == sha256_text(MAPPER)


def test_a_changed_template_changes_the_hash(make: Callable[..., PromptLoader]) -> None:
    assert (
        make().load("mapper").prompt_hash
        != make({"mapper.v1.md": MAPPER + "\nextra"}).load("mapper").prompt_hash
    )


def test_the_version_comes_from_settings_and_selects_the_file(
    make: Callable[..., PromptLoader],
) -> None:
    v2 = MAPPER.replace("version: v1", "version: v2").replace("meticulous", "careful")
    loader = make({"mapper.v1.md": MAPPER, "mapper.v2.md": v2}, mapper="v2")
    assert "careful" in loader.render("mapper", **VARS).messages[0].content
    assert loader.load("mapper").meta.version == "v2"


def test_prompts_are_parsed_once(make: Callable[..., PromptLoader]) -> None:
    loader = make()
    assert loader.load("mapper") is loader.load("mapper")


def test_front_matter_metadata_is_exposed(make: Callable[..., PromptLoader]) -> None:
    meta = make().load("mapper").meta
    assert (meta.id, meta.version, meta.output_model) == ("mapper", "v1", "DraftFinding")


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("## system\nhi\n", "missing front-matter"),
        ("---\nid: mapper\n---\n## user\nhi\n", "invalid front-matter"),
        (
            "---\nid: mapper\nversion: v1\noutput_model: X\nextra: 1\n---\n## user\nhi\n",
            "invalid front-matter",
        ),
        ("---\nid: [unclosed\n---\n## user\nhi\n", "invalid front-matter"),
        (
            "---\nid: other\nversion: v1\noutput_model: X\n---\n## user\nhi\n",
            "says other v1, expected mapper v1",
        ),
        (
            "---\nid: mapper\nversion: v9\noutput_model: X\n---\n## user\nhi\n",
            "says mapper v9, expected mapper v1",
        ),
        ("---\nid: mapper\nversion: v1\noutput_model: X\n---\nno headings\n", "needs at least one"),
        (
            "---\nid: mapper\nversion: v1\noutput_model: X\n---\nstray\n## user\nhi\n",
            "text before the first section",
        ),
        (
            "---\nid: mapper\nversion: v1\noutput_model: X\n---\n## user\n\n## system\nhi\n",
            "'## user' section is empty",
        ),
        (
            "---\nid: mapper\nversion: v1\noutput_model: X\n---\n## user\n{% if %}\n",
            r"mapper\.v1\.md, line",
        ),
        (
            "---\nid: mapper\nversion: v1\noutput_model: X\n---\n## user\n{{ a\n",
            r"mapper\.v1\.md, line",
        ),
    ],
)
def test_bad_prompt_files_give_clear_errors(
    make: Callable[..., PromptLoader], text: str, match: str
) -> None:
    with pytest.raises(ConfigError, match=match):
        make({"mapper.v1.md": text}).load("mapper")


def test_missing_file_and_unknown_prompt_names(make: Callable[..., PromptLoader]) -> None:
    loader = make({})
    with pytest.raises(ConfigError, match=r"cannot read prompt file mapper\.v1\.md"):
        loader.load("mapper")
    for name in ("poem", "__class__", "model_fields"):
        with pytest.raises(ConfigError, match="unknown prompt"):
            loader.load(name)


def test_only_a_user_or_only_a_system_section_is_allowed(make: Callable[..., PromptLoader]) -> None:
    head = "---\nid: mapper\nversion: v1\noutput_model: X\n---\n"
    only_user = make({"mapper.v1.md": head + "## user\nHello {{ who }}\n"}).render(
        "mapper", who="you"
    )
    assert [(m.role, m.content) for m in only_user.messages] == [("user", "Hello you")]
    both = make({"mapper.v1.md": head + "## user\nu\n## system\ns\n## user\nu2\n"}).render("mapper")
    assert [m.role for m in both.messages] == [
        "user",
        "system",
        "user",
    ]  # order of the file is kept


def test_rendered_messages_are_chat_messages(make: Callable[..., PromptLoader]) -> None:
    assert all(isinstance(m, ChatMessage) for m in make().render("mapper", **VARS).messages)


def test_rendering_is_deterministic(make: Callable[..., PromptLoader]) -> None:
    loader = make()
    assert loader.render("mapper", **VARS) == loader.render("mapper", **VARS)
