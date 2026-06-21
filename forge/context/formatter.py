from __future__ import annotations

import math


def estimate_tokens(value: str) -> int:
    return math.ceil(len(value) / 4)

