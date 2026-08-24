from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.user_provisioning import generate_password
from app.version import __version__

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["app_version"] = __version__
templates.env.globals["app_name"] = get_settings().app_name
# Lets any template call generate_password() directly (e.g. the Reset
# Password modal's initial value in ad/search.html) without every route
# that renders such a template needing to pass it through explicitly.
templates.env.globals["generate_password"] = generate_password
