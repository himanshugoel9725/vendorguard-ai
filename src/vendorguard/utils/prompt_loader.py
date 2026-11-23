"""Versioned prompt files: ``prompts/<name>.<version>.md`` with front-matter and role sections.

A file looks like (docs/PLAN.md section 8)::

    ---
    id: mapper
    version: v1
    output_model: DraftFinding
    ---
    ## system
    ...Jinja text...
    ## user
    ...Jinja text...

The version of each prompt comes from ``settings.prompts``. Templates are rendered in a sandbox with
strict undefined handling, so a missing variable is an error and the *contents* of variables (for
example untrusted document text) are never interpreted as template code.
"""

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from jinja2 import StrictUndefined, TemplateError, TemplateSyntaxError, UndefinedError
from jinja2.exceptions import SecurityError
from jinja2.sandbox import SandboxedEnvironment
from pydantic import ValidationError

from vendorguard.config_models.core import PromptsSettings
from vendorguard.errors import ConfigError
from vendorguard.models._base import ContractModel, NonEmptyStr
from vendorguard.models.llm import ChatMessage
from vendorguard.utils.hashing import sha256_text

Role = Literal["system", "user"]
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_SECTION = re.compile(r"^## (system|user)[ \t]*$", re.MULTILINE)
MAX_SEQUENCE = (
    100_000  # longest string or list a template may build with ``*`` (as Jinja's range limit)
)
MAX_EXPONENT = 1_000  # largest exponent a template may use with ``**``


class _LimitedSandbox(SandboxedEnvironment):
    """Jinja's sandbox plus size limits on ``*`` and ``**``, so a template cannot exhaust memory."""

    intercepted_binops = frozenset({"*", "**"})

    def call_binop(self, context: Any, operator: str, left: Any, right: Any) -> Any:
        """Refuse results that would be huge; everything else is evaluated as usual."""
        if operator == "*":
            for sequence, count in ((left, right), (right, left)):
                if (
                    isinstance(sequence, str | bytes | list | tuple)
                    and isinstance(count, int)
                    and len(sequence) * max(count, 0) > MAX_SEQUENCE
                ):
                    raise SecurityError(f"a template may not build more than {MAX_SEQUENCE} items")
        elif isinstance(right, int) and abs(right) > MAX_EXPONENT:
            raise SecurityError(f"a template may not use an exponent above {MAX_EXPONENT}")
        return super().call_binop(context, operator, left, right)


_ENV = _LimitedSandbox(
    undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True
)


class PromptMeta(ContractModel):
    """The front-matter of a prompt file."""

    id: NonEmptyStr
    version: NonEmptyStr
    output_model: NonEmptyStr


class RenderedPrompt(ContractModel):
    """Messages ready for an LLM client, and the hash of the template they came from."""

    messages: list[ChatMessage]
    prompt_hash: str


class Prompt:
    """One parsed prompt file."""

    def __init__(
        self, meta: PromptMeta, sections: list[tuple[Role, str]], prompt_hash: str
    ) -> None:
        self.meta = meta
        self.prompt_hash = prompt_hash
        self._templates = [(role, _ENV.from_string(text)) for role, text in sections]

    def render(self, **variables: Any) -> RenderedPrompt:
        """Fill the template; raises ConfigError naming a variable that was not supplied."""
        try:
            messages = [
                ChatMessage(role=role, content=template.render(**variables).strip())
                for role, template in self._templates
            ]
        except UndefinedError as exc:
            raise ConfigError(
                f"prompt '{self.meta.id}' {self.meta.version}: {exc.message}"
            ) from exc
        except TemplateError as exc:
            raise ConfigError(
                f"prompt '{self.meta.id}' {self.meta.version} cannot be rendered: {exc}"
            ) from exc
        except Exception as exc:  # TypeError (no loader), OverflowError (range), broken variables
            raise ConfigError(
                f"prompt '{self.meta.id}' {self.meta.version} cannot be rendered "
                f"({type(exc).__name__})"
            ) from exc
        return RenderedPrompt(messages=messages, prompt_hash=self.prompt_hash)


class PromptLoader:
    """Finds, parses and caches the prompt files of one run."""

    def __init__(self, prompts_dir: Path, versions: PromptsSettings) -> None:
        self._dir = prompts_dir
        self._versions = versions
        self._loaded: dict[str, Prompt] = {}

    def load(self, name: str) -> Prompt:
        """The prompt ``name`` at the version configured in ``settings.prompts``."""
        if name not in self._loaded:
            self._loaded[name] = self._parse(name)
        return self._loaded[name]

    def render(self, name: str, **variables: Any) -> RenderedPrompt:
        """``load(name).render(**variables)``."""
        return self.load(name).render(**variables)

    def _parse(self, name: str) -> Prompt:
        if name not in type(self._versions).model_fields:
            raise ConfigError(f"unknown prompt '{name}': add it to the prompts section of settings")
        version = getattr(self._versions, name)
        path = self._dir / f"{name}.{version}.md"
        try:
            text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        except OSError as exc:
            raise ConfigError(f"cannot read prompt file {path.name}: {type(exc).__name__}") from exc
        match = _FRONT_MATTER.match(text)
        if not match:
            raise ConfigError(f"{path.name}: missing front-matter (--- ... ---) at the top")
        try:
            meta = PromptMeta.model_validate(yaml.safe_load(match.group(1)))
        except (yaml.YAMLError, ValidationError) as exc:
            raise ConfigError(f"{path.name}: invalid front-matter ({type(exc).__name__})") from exc
        if (meta.id, meta.version) != (name, version):
            raise ConfigError(
                f"{path.name}: front-matter says {meta.id} {meta.version}, "
                f"expected {name} {version}"
            )
        sections = _sections(path.name, match.group(2))
        try:
            return Prompt(meta, sections, sha256_text(text))
        except TemplateSyntaxError as exc:
            raise ConfigError(f"{path.name}, line {exc.lineno}: {exc.message}") from exc


def _sections(filename: str, body: str) -> list[tuple[Role, str]]:
    marks = list(_SECTION.finditer(body))
    if not marks:
        raise ConfigError(f"{filename}: needs at least one '## system' or '## user' section")
    if body[: marks[0].start()].strip():
        raise ConfigError(f"{filename}: text before the first section heading")
    sections: list[tuple[Role, str]] = []
    for mark, following in zip(marks, [*marks[1:], None], strict=True):
        text = body[mark.end() : following.start() if following else len(body)].strip()
        if not text:
            raise ConfigError(f"{filename}: the '## {mark.group(1)}' section is empty")
        sections.append((mark.group(1), text))  # type: ignore[arg-type]
    return sections


__all__ = ["Prompt", "PromptLoader", "PromptMeta", "RenderedPrompt"]
