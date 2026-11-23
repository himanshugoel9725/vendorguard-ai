"""Base class and constrained types shared by every data contract."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Base for data contracts: unknown fields are errors and instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


Probability = Annotated[float, Field(ge=0.0, le=1.0)]
Score100 = Annotated[float, Field(ge=0.0, le=100.0)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmptyStr = Annotated[str, Field(min_length=1)]
NonNegInt = Annotated[int, Field(ge=0)]

__all__ = ["ContractModel", "NonEmptyStr", "NonNegInt", "Probability", "Score100", "Sha256"]
