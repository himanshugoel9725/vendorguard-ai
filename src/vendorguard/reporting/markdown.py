"""Markdown report. Every text that came from a document or a model is escaped."""

import re
from typing import Any

_SPECIAL = re.compile(r"([\\`*_{}\[\]<>#|~&])")


def md(text: object) -> str:
    """One line of plain text that cannot start markup, links, tables or HTML."""
    return _SPECIAL.sub(r"\\\1", " ".join(str(text).split()))


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
    return lines + ["| " + " | ".join(r) + " |" for r in rows] + [""]


def _finding(f: dict[str, Any]) -> list[str]:
    lines = [f"### {md(f['id'])}: {md(f['title'])}", "", f"**{md(f['status_label'])}**"]
    if f["override"]:
        o = f["override"]
        lines[-1] += (
            f" (analyst override by {md(o['analyst'])}; system said {md(f['system_label'])})"
        )
        lines += ["", f"Override reason: {md(o['reason'])}"]
    lines += ["", md(f["rationale"]), ""]
    for c in f["citations"]:
        page = f", page {c['page']}" if c["page"] else ""
        lines.append(f"> {md(c['quote'])} ({md(c['document'])}{page})")
        lines.append("")
    return lines


def _overrides(v: dict[str, Any]) -> list[str]:
    if not v["overrides"]:
        return []
    rows = [
        f"- {md(f['id'])}: {md(f['status_label'])} by {md(f['override']['analyst'])}"
        for f in v["overrides"]
    ]
    return ["## Analyst overrides", "", *rows, ""]


def _audit(v: dict[str, Any]) -> list[str]:
    a = v["audit"]
    if not a:
        return []
    text = (
        f"{a['events']} recorded steps, {a['cached']} replayed from cache, "
        f"{a['tokens_in']} tokens in, {a['tokens_out']} out, ${a['usd']:g}, "
        f"{a['fallbacks']} fallbacks."
    )
    return ["## Audit summary", "", text, ""]


MANIFEST_KEYS = (
    "status",
    "app_version",
    "git_sha",
    "config_fingerprint",
    "controls_version",
    "result_hash",
)


def _manifest(v: dict[str, Any]) -> list[str]:
    m = v["manifest"]
    if not m:
        return []
    rows = [f"- {md(k)}: {md(m[k])}" for k in MANIFEST_KEYS]
    for i in m["inputs"]:
        rows.append(f"- input: {md(i['filename'])} (sha256 {md(i['sha256'])}, {i['pages']} pages)")
    return ["## Run manifest", "", *rows]


def render_markdown(view: dict[str, Any]) -> str:
    """The full report as Markdown text."""
    v = view
    out = [
        f"# Vendor risk assessment: {md(v['vendor_name'])}",
        "",
        f"Run {md(v['run_id'])} · {md(v['created_at'])} · vendor {md(v['vendor_id'])}",
        "",
        "## Summary",
        "",
        md(v["summary"]),
        "",
        f"**Risk score {v['overall']:g} / 100, band {md(v['band'])}.** "
        f"Inherent risk: {md(v['inherent_tier'])} ({md(', '.join(v['inherent_reasons']))}).",
        "",
    ]
    out += [f"- Rule triggered: {md(r)}" for r in v["triggered_rules"]]
    out += ["", "## Domain risk scores", ""]
    out += _table(
        ["Domain", "Risk score"], [[md(d["name"]), f"{d['score']:g}"] for d in v["domains"]]
    )
    out += ["## Status counts", ""]
    out += _table(["Status", "Controls"], [[md(c["label"]), str(c["n"])] for c in v["counts"]])
    out += ["## Findings", ""]
    out += _table(
        ["Control", "Title", "Status"],
        [[md(f["id"]), md(f["title"]), md(f["status_label"])] for f in v["findings"]],
    )
    for f in v["findings"]:
        out += _finding(f)
    if v["diff"]:
        d = v["diff"]
        out += ["## Changes since the previous assessment", ""]
        out.append(f"Previous run {md(d['previous_run_id'])}; score change {d['score_delta']:+g}.")
        out += ["", f"- New gaps: {md(', '.join(d['new_gaps']) or 'none')}"]
        out += [f"- Resolved gaps: {md(', '.join(d['resolved_gaps']) or 'none')}", ""]
        out += [
            f"- {md(c['control_id'])}: {md(c['from_status'])} to {md(c['to_status'])}"
            for c in d["changed"]
        ] + [""]
    out += _overrides(v) + _audit(v) + _manifest(v)
    return "\n".join(out).rstrip() + "\n"


__all__ = ["md", "render_markdown"]
