"""
API module - FastAPI application factory and routes.
"""

from fastapi import FastAPI

from .routes import router


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance
    """
    app = FastAPI(
        title="Hanna-Med RPA Agent",
        description="RPA Agent for medical patient list capture",
        version="1.1.0",
    )

    # Register middleware
    @app.middleware("http")
    async def log_requests(request, call_next):
        print(f"[API] {request.method} {request.url.path}")
        response = await call_next(request)
        return response

    # Register routes
    app.include_router(router)

    return app


# Create default app instance for backwards compatibility
app = create_app()

__all__ = ["create_app", "app"]
