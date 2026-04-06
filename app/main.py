from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.api import api_router
from app.core.config import settings


def get_application() -> FastAPI:
    _app = FastAPI(
        title=settings.PROJECT_NAME,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        debug=settings.DEBUG,
    )

    _app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _app.include_router(api_router, prefix=settings.API_V1_STR)

    return _app


app = get_application()


@app.get("/")
def root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}"}
