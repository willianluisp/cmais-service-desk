class PortalSecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' blob:; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'self'; object-src 'none'"
        ))
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        return response
