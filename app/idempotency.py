import hashlib
import json
from typing import Any


def request_hash(body: Any) -> str:
    serialized = json.dumps(body.model_dump(), sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()