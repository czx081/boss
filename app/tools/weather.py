import hashlib
from typing import Dict


CONDITIONS = ["晴", "多云", "小雨", "阴"]


def get_weather(city: str) -> Dict[str, object]:
    normalized = city.strip()
    if not normalized:
        raise ValueError("City cannot be empty")
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    temperature = 12 + digest[0] % 22
    condition = CONDITIONS[digest[1] % len(CONDITIONS)]
    return {
        "city": normalized,
        "temperature_c": temperature,
        "condition": condition,
        "source": "mock",
    }

