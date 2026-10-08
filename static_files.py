from starlette.staticfiles import StaticFiles


class NoCacheStaticFiles(StaticFiles):
    """Serve assets with `no-cache` so UI updates load without a hard refresh."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response
