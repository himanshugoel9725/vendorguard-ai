"""Run identifiers: deterministic (hash of inputs + config) or random, chosen by configuration."""

import uuid
from collections.abc import Iterable

from vendorguard.utils.hashing import hash_obj

RUN_ID_PREFIX = "run_"
RUN_ID_HEX_CHARS = 12


def make_run_id(
    vendor_id: str,
    input_hashes: Iterable[str],
    config_fingerprint: str,
    *,
    deterministic: bool,
) -> str:
    """Return ``run_<12 hex>``: the same vendor, inputs and config give the same ID when deterministic.

    Pass ``pipeline.deterministic_run_ids`` as ``deterministic``. Random IDs are the one place
    unseeded randomness is allowed, because the setting asks for unique runs.
    """
    if deterministic:
        digest = hash_obj(
            {"vendor": vendor_id, "inputs": sorted(input_hashes), "config": config_fingerprint}
        )
    else:
        digest = uuid.uuid4().hex
    return RUN_ID_PREFIX + digest[:RUN_ID_HEX_CHARS]


__all__ = ["make_run_id"]
