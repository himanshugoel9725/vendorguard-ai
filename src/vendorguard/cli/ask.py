"""``vg ask``: ask a question about a vendor's assessment history."""

from typing import Annotated

import typer

from vendorguard.agents.ask import AskAgent
from vendorguard.cli.common import console, guarded, load, open_memory
from vendorguard.factory import build_providers
from vendorguard.observability.audit_log import AuditLog
from vendorguard.utils.prompt_loader import PromptLoader


@guarded
def ask(
    vendor: Annotated[str, typer.Argument(help="Vendor id, e.g. nimbara-hr.")],
    question: Annotated[str, typer.Argument(help="Your question about the vendor's history.")],
    llm: Annotated[
        str | None, typer.Option(help="ollama | openai | groq | openai_compat | mock")
    ] = None,
) -> None:
    """Answer from the stored assessments; the answer cites run and control IDs."""
    settings = load({"llm": {"provider": llm}} if llm else None)
    providers = build_providers(settings)
    try:
        with open_memory(settings) as memory:
            agent = AskAgent(
                providers.llm,
                PromptLoader(settings.paths.prompts_dir, settings.prompts),
                AuditLog(settings.paths.state_dir / "ask.audit.jsonl", "ask"),
                providers.tracker,
                memory,
                settings.memory,
                settings.reporting,
            )
            answer = agent.ask(vendor, question)
    finally:
        providers.close()
    console.print(answer.text, markup=False, soft_wrap=True)
    cited = [*answer.cited_run_ids, *answer.cited_control_ids]
    if cited:
        console.print(f"cited: {', '.join(cited)}", markup=False, soft_wrap=True)


__all__ = ["ask"]
