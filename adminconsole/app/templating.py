from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.version import __version__

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["app_version"] = __version__
templates.env.globals["app_name"] = get_settings().app_name
