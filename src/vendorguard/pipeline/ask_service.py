"""One question about a vendor's history: shared by ``vg ask`` and the REST API."""

from vendorguard.agents.ask import AskAgent
from vendorguard.config import Settings
from vendorguard.factory import build_providers
from vendorguard.interfaces.memory import MemoryStore
from vendorguard.models.run import Answer
from vendorguard.observability.audit_log import AuditLog
from vendorguard.utils.hashing import hash_obj
from vendorguard.utils.prompt_loader import PromptLoader
from vendorguard.utils.timeutil import utcnow

ASK_ID_CHARS = 12


def answer_question(
    settings: Settings, memory: MemoryStore, vendor_id: str, question: str
) -> Answer:
    """Answer ``question`` from the stored runs of ``vendor_id``.

    Builds its own providers (the cost budget is per call) and writes one audit file of its own
    under ``paths.state_dir/ask/``. The memory store is the caller's and is not closed.
    """
    ask_id = (
        "ask_"
        + hash_obj({"vendor": vendor_id, "question": question, "at": utcnow().isoformat()})[
            :ASK_ID_CHARS
        ]
    )
    providers = build_providers(settings)
    try:
        agent = AskAgent(
            providers.llm,
            PromptLoader(settings.paths.prompts_dir, settings.prompts),
            AuditLog(settings.paths.state_dir / "ask" / f"{ask_id}.jsonl", ask_id),
            providers.tracker,
            memory,
            settings.memory,
            settings.reporting,
        )
        return agent.ask(vendor_id, question)
    finally:
        providers.close()


__all__ = ["answer_question"]
