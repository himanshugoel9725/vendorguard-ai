"""Turn a spec, the phrase bank and the control set into pages of blocks plus an evidence map."""

from vendorguard.config_models.core import SamplesSettings
from vendorguard.eval.sample_gen.layout import block_cost
from vendorguard.eval.sample_gen.models import Block, ComposedSample, EvidenceEntry, PhraseBank
from vendorguard.eval.sample_gen.variants import pick_index
from vendorguard.eval.specs import SampleState, VendorSpec
from vendorguard.models.control import Control, ControlSet

INJECTION_AFTER_CONTROLS = 2  # the injection paragraph follows the second control paragraph


def _cover(spec: VendorSpec, bank: PhraseBank) -> list[Block]:
    """Cover page; it avoids control keywords so only control sentences decide a status."""
    data = "; ".join(bank.data_category_phrases[c] for c in spec.data_categories)
    lines = [
        f"Reporting period: {spec.report_period}.",
        " ".join(spec.summary.split()),
        f"Services: {'; '.join(spec.services)}.",
        f"Hosting: {'; '.join(spec.hosting)}.",
        f"Data handled: {data}.",
    ]
    if spec.subprocessors:
        lines.append(f"Key suppliers: {'; '.join(spec.subprocessors)}.")
    if spec.certifications:
        lines.append(f"Independent reports held: {'; '.join(spec.certifications)}.")
    return [
        Block(kind="title", text="Security & Trust Overview"),
        Block(kind="subtitle", text=spec.vendor_name),
        *[Block(kind="body", text=t) for t in lines],
    ]


def _section(
    number: int, domain: str, spec: VendorSpec, bank: PhraseBank, controls: list[Control]
) -> tuple[list[Block], dict[str, EvidenceEntry]]:
    base = spec.based_on or spec.vendor_id
    evidence: dict[str, EvidenceEntry] = {}
    filler = bank.filler[domain]
    distractors = bank.distractors[domain]
    blocks = [
        Block(kind="heading", text=f"Section {number}: {bank.section_titles[domain]}"),
        Block(kind="body", text=filler[pick_index(base, domain, "filler", len(filler))]),
    ]
    injected = spec.injection is None or spec.injection.section != domain
    for count, control in enumerate(controls, start=1):
        state = spec.controls[control.id]
        if state is SampleState.MISSING:
            evidence[control.id] = EvidenceEntry(state=state)
        else:
            options = getattr(bank.controls[control.id], state.value)
            variant = pick_index(base, control.id, state.value, len(options))
            blocks.append(Block(kind="body", text=options[variant], control_id=control.id))
            evidence[control.id] = EvidenceEntry(
                state=state, sentence=options[variant], variant=variant
            )
        if not injected and spec.injection and count == INJECTION_AFTER_CONTROLS:
            blocks.append(Block(kind="injection", text=" ".join(spec.injection.text.split())))
            injected = True
    if not injected and spec.injection:
        blocks.append(Block(kind="injection", text=" ".join(spec.injection.text.split())))
    blocks.append(
        Block(
            kind="body", text=distractors[pick_index(base, domain, "distractor", len(distractors))]
        )
    )
    return blocks, evidence


def _paginate(blocks: list[Block], settings: SamplesSettings) -> list[list[Block]]:
    """Fill pages by line budget; blocks are never split and a heading stays with its paragraph."""
    pages: list[list[Block]] = [[]]
    used = 0
    for index, block in enumerate(blocks):
        cost = block_cost(block, settings.wrap_chars)
        if block.kind == "heading" and index + 1 < len(blocks):
            cost += block_cost(blocks[index + 1], settings.wrap_chars)
        if pages[-1] and used + cost > settings.lines_per_page:
            pages.append([])
            used = 0
        pages[-1].append(block)
        used += block_cost(block, settings.wrap_chars)
    return pages


def compose(
    spec: VendorSpec, bank: PhraseBank, controls: ControlSet, settings: SamplesSettings
) -> ComposedSample:
    """Compose the whole document: the cover on page 1, then each domain starting on a new page."""
    pages = [_cover(spec, bank)]
    evidence: dict[str, EvidenceEntry] = {}
    for number, domain in enumerate(controls.domains, start=1):
        in_domain = sorted((c for c in controls.controls if c.domain == domain), key=lambda c: c.id)
        blocks, found = _section(number, domain, spec, bank, in_domain)
        first_page = len(pages) + 1
        section_pages = _paginate(blocks, settings)
        pages.extend(section_pages)
        for offset, page in enumerate(section_pages):
            for block in page:
                if block.control_id:
                    found[block.control_id] = found[block.control_id].model_copy(
                        update={"page": first_page + offset}
                    )
        evidence.update(found)
    return ComposedSample(pages=pages, evidence=dict(sorted(evidence.items())))


__all__ = ["compose"]
