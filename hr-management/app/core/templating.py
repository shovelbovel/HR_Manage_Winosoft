import json
from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _tojson(value: object) -> Markup:
    # Plain Jinja2 (unlike Flask) has no built-in `tojson` filter; needed to
    # hand chart data (department/contract-type distributions) to Chart.js
    # as an inline JS literal.
    return Markup(json.dumps(value, default=str))


templates.env.filters["tojson"] = _tojson
