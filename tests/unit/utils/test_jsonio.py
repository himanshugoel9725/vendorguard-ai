"""Tests for vendorguard.utils.jsonio, including cross-process determinism."""

import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path

import pytest
from pydantic import BaseModel, SecretStr

from vendorguard.utils.jsonio import canonical_json, normalize, read_json, write_json


class Color(Enum):
    RED = "red"


class Inner(BaseModel):
    name: str
    tags: set[str]


class Outer(BaseModel):
    inner: Inner
    items: list[Inner]


class Holder(BaseModel):
    secret: SecretStr


def test_sorted_keys_and_compact() -> None:
    assert canonical_json({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'


def test_ascii_only() -> None:
    out = canonical_json({"k": "é日"})
    assert out == '{"k":"\\u00e9\\u65e5"}'
    assert out.isascii()


def test_float_rounding() -> None:
    assert canonical_json(0.30000000000000004) == "0.3"
    assert canonical_json(1.23456789) == "1.234568"


def test_negative_zero() -> None:
    assert canonical_json(-0.0) == "0.0"


def test_scalars_unchanged() -> None:
    assert canonical_json([1, True, False, None, "x"]) == '[1,true,false,null,"x"]'
    assert normalize(True) is True
    assert normalize(10**30) == 10**30


def test_tuple_and_sets() -> None:
    assert normalize((1, 2)) == [1, 2]
    assert normalize({3, 1, 2}) == [1, 2, 3]
    assert normalize(frozenset({"b", "a"})) == ["a", "b"]
    assert normalize({"b", "a", "c"}) == ["a", "b", "c"]
    assert normalize({2, "a", 1, "b"}) == normalize({"b", 1, "a", 2})
    assert len(normalize({2, "a", 1, "b"})) == 4


def test_enum_datetime_date_path() -> None:
    assert normalize(Color.RED) == "red"
    assert normalize(datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)) == "2024-01-02T03:04:05+00:00"
    assert normalize(date(2024, 1, 2)) == "2024-01-02"
    assert normalize(Path("a") / "b") == "a/b"


def test_nested_pydantic_with_set() -> None:
    model = Outer(
        inner=Inner(name="n", tags={"z", "a", "m"}), items=[Inner(name="i", tags={"y", "x"})]
    )
    assert normalize(model) == {
        "inner": {"name": "n", "tags": ["a", "m", "z"]},
        "items": [{"name": "i", "tags": ["x", "y"]}],
    }


def test_nested_structures_and_non_str_keys() -> None:
    assert canonical_json({1: {"a": [(1, {2, 1})]}}) == '{"1":{"a":[[1,[1,2]]]}}'


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_raises(bad: float) -> None:
    with pytest.raises(ValueError):
        canonical_json(bad)
    with pytest.raises(ValueError):
        canonical_json({"x": [bad]})


def test_unknown_type_raises() -> None:
    with pytest.raises(TypeError):
        canonical_json(object())


def test_secretstr_raises() -> None:
    with pytest.raises(TypeError):
        canonical_json(Holder(secret=SecretStr("hunter2")))


def test_write_and_read_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "out.json"
    value = {"z": 1, "a": [0.1 + 0.2, "é"]}
    write_json(target, value)
    text = target.read_text(encoding="utf-8")
    assert text == canonical_json(value) + "\n"
    assert read_json(target) == {"z": 1, "a": [0.3, "é"]}


def test_normalize_output_is_plain_json() -> None:
    model = Outer(inner=Inner(name="n", tags={"b"}), items=[])
    out = normalize({"m": model, "e": Color.RED, "s": {1}, "t": (1,), "p": Path("x")})
    assert json.loads(json.dumps(out)) == out


_SCRIPT = """
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from pydantic import BaseModel
from vendorguard.utils.hashing import hash_obj
from vendorguard.utils.ids import make_run_id

class Color(Enum):
    RED = "red"

class M(BaseModel):
    tags: set[str]
    nums: frozenset[int]

obj = {
    "nested": {"b": {"z", "y", "x", 3, 1}, "a": [1, (2, 3)]},
    "model": M(tags={"q", "w", "e", "r"}, nums=frozenset({5, 4, 9})),
    "color": Color.RED,
    "path": Path("a/b"),
    "when": datetime(2024, 5, 6, 7, 8, 9, tzinfo=UTC),
    "f": 0.1 + 0.2,
    "big": 10**30,
    "mixed": {"k", 2, "j", 1},
}
print(hash_obj(obj))
print(make_run_id("v", [hash_obj(obj), "h2"], "fp", deterministic=True))
"""


@pytest.mark.parametrize("seed", ["0", "1", "42", "random"])
def test_cross_process_determinism(seed: str) -> None:
    def run(s: str) -> list[str]:
        proc = subprocess.run(
            [sys.executable, "-c", _SCRIPT],
            env={**os.environ, "PYTHONHASHSEED": s},
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.split()

    outputs = run(seed)
    assert len(outputs) == 2
    assert outputs == run("0")
    assert outputs == run("random")


def test_cross_process_matches_in_process() -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        env={**os.environ, "PYTHONHASHSEED": "7"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    printed = proc.stdout.split()

    captured: list[str] = []
    namespace = {"__name__": "_script"}
    code = _SCRIPT.replace("print(", "_capture(")
    namespace["_capture"] = captured.append
    exec(compile(code, "<script>", "exec"), namespace)  # noqa: S102
    assert printed == captured
