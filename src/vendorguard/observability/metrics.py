"""Prometheus metrics of the process, on a private registry (never the global one)."""

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

from vendorguard.config_models.core import ObservabilitySettings
from vendorguard.models.audit import AuditEvent

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class Metrics:
    """Counters and histograms fed by audit events and run results; render for ``/metrics``."""

    def __init__(
        self, settings: ObservabilitySettings, registry: CollectorRegistry | None = None
    ) -> None:
        self.registry = registry or CollectorRegistry()
        self._runs = Counter("vg_runs_total", "Finished runs", ["status"], registry=self.registry)
        self._steps = Counter(
            "vg_steps_total", "Recorded steps", ["stage", "cached"], registry=self.registry
        )
        self._tokens = Counter(
            "vg_tokens_total", "Model tokens", ["direction"], registry=self.registry
        )
        self._usd = Counter("vg_cost_usd_total", "Spend in USD", registry=self.registry)
        self._latency = Histogram(
            "vg_step_latency_seconds",
            "Latency of a recorded step",
            ["stage"],
            buckets=tuple(settings.latency_buckets_s),
            registry=self.registry,
        )

    def observe_event(self, event: AuditEvent) -> None:
        """Count one audit event (usable as ``AuditLog(on_event=...)``)."""
        self._steps.labels(stage=event.stage, cached=str(event.cached).lower()).inc()
        self._tokens.labels(direction="in").inc(event.tokens_in)
        self._tokens.labels(direction="out").inc(event.tokens_out)
        self._usd.inc(max(event.usd, 0.0))
        self._latency.labels(stage=event.stage).observe(max(event.latency_ms, 0.0) / 1000.0)

    def run_finished(self, status: str) -> None:
        """Count a finished run (done or failed)."""
        self._runs.labels(status=status).inc()

    def render(self) -> bytes:
        """The text exposition format."""
        return generate_latest(self.registry)


__all__ = ["CONTENT_TYPE", "Metrics"]
