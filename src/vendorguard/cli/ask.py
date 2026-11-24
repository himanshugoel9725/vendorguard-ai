"""``vg ask``: ask a question about a vendor's assessment history."""

from typing import Annotated

import typer

from vendorguard.cli.common import console, guarded, load, open_memory
from vendorguard.pipeline.ask_service import answer_question


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
    with open_memory(settings) as memory:
        answer = answer_question(settings, memory, vendor, question)
    console.print(answer.text, markup=False, soft_wrap=True)
    cited = [*answer.cited_run_ids, *answer.cited_control_ids]
    if cited:
        console.print(f"cited: {', '.join(cited)}", markup=False, soft_wrap=True)


__all__ = ["ask"]
