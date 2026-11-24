"""Static checks of the Docker files (Docker itself is not needed): the properties that matter
for safety must not regress silently."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
IGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
API = COMPOSE["services"]["api"]


def _instructions(name: str) -> list[str]:
    return [ln.strip() for ln in DOCKERFILE.splitlines() if ln.strip().startswith(name)]


def test_the_image_runs_as_a_non_root_user_and_ends_on_it() -> None:
    users = _instructions("USER")
    assert users and users[-1] != "USER root" and users[-1] != "USER 0"
    assert "--uid 10001" in DOCKERFILE


def test_the_image_has_a_healthcheck_on_the_public_endpoint() -> None:
    assert _instructions("HEALTHCHECK") and "/health" in DOCKERFILE


def test_no_secret_is_baked_into_the_image_or_the_compose_file() -> None:
    text = DOCKERFILE + (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert not re.search(
        r"(?i)(api_key|auth_key|password|secret|token)\s*[:=]\s*\S+[A-Za-z0-9]{8}", text
    )
    assert "COPY .env" not in DOCKERFILE and not re.search(r"COPY\s+\.\s", DOCKERFILE)


def test_the_build_context_excludes_secrets_state_and_bulk() -> None:
    for entry in (".env", ".git", ".venv*", ".vendorguard", "data", "tests"):
        assert entry in IGNORE
    assert "!.env.example" in IGNORE


def test_the_image_is_installed_not_editable_and_pins_its_tools() -> None:
    assert "--frozen" in DOCKERFILE and "--no-dev" in DOCKERFILE and "--no-editable" in DOCKERFILE
    assert re.search(r"UV_IMAGE=ghcr\.io/astral-sh/uv:\d+\.\d+\.\d+", DOCKERFILE)
    assert "VENDORGUARD_CONFIG=/app/config/settings.yaml" in DOCKERFILE  # no repo-relative default


def test_the_server_binds_all_interfaces_only_inside_the_container() -> None:
    assert "VG_API__HOST=0.0.0.0" in DOCKERFILE
    ports = API["ports"]
    assert ports and all(str(p).startswith("127.0.0.1:") for p in ports)  # published on loopback


def test_compose_service_is_hardened_and_behind_a_profile() -> None:
    assert API["profiles"] == ["api"]
    assert API["read_only"] is True and "ALL" in API["cap_drop"]
    assert "no-new-privileges:true" in API["security_opt"]
    assert any(str(v).endswith(":/data") for v in API["volumes"])
    assert API["env_file"][0]["path"] == ".env"  # keys come from .env at run time
    assert "letta" not in COMPOSE["services"]  # ADR-019: not built


def test_the_container_reaches_ollama_on_the_host() -> None:
    env = API["environment"]
    assert "host.docker.internal" in env["VG_LLM__BASE_URL"]
    assert "host.docker.internal:host-gateway" in API["extra_hosts"]
