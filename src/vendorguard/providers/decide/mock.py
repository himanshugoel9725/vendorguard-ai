"""Mock decider for tests and offline demos: the keyword rules under the name ``mock``."""

from vendorguard.providers.decide.rule import RuleDecider


class MockDecider(RuleDecider):
    """Same deterministic rules as ``RuleDecider``; only the provider name differs."""

    name = "mock"


__all__ = ["MockDecider"]
