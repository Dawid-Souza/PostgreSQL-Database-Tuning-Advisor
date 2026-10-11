from __future__ import annotations

import json
from typing import Any

from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR


def pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.filters["pretty_json"] = pretty_json

