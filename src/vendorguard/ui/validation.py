"""Input checks that mirror the API's patterns (a test keeps them equal to the server's)."""

import re

VENDOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CONTROL_ID_PATTERN = re.compile(r"^[A-Za-z]{2,5}-\d{2,3}$")

__all__ = ["CONTROL_ID_PATTERN", "RUN_ID_PATTERN", "VENDOR_ID_PATTERN"]
