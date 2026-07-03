from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from core.config import settings
from core.deps import RequiresLoginException
from routers import auth, mail

app = FastAPI(title="EmailClient")

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    max_age=60 * 60 * 24 * 7,
    https_only=settings.APP_BASE_URL.startswith("https"),
)

app.include_router(auth.router, prefix="/auth")
app.include_router(mail.router)


@app.exception_handler(RequiresLoginException)
async def requires_login(request: Request, exc: RequiresLoginException):
    return RedirectResponse(url="/auth/login")


@app.get("/")
async def root():
    return RedirectResponse(url="/mail")
