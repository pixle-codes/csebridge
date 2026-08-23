"""CSE-style error surface: every failure becomes a Google-shaped error dict."""

CSE_ERROR_TEMPLATE = "https://www.googleapis.com/customsearch/v1?q=%s&cx=%s"


class CseError(Exception):
    """Raised for backend/network/usage failures.

    `.payload` is the exact JSON shape the real CSE API returns on error,
    so handlers written against the old API keep working unchanged.
    """

    def __init__(self, message, code=500, reason="backendError", status=None):
        super().__init__(message)
        self.code = int(code)
        self.reason = reason
        self.payload = {
            "error": {
                "code": self.code,
                "message": message,
                "errors": [
                    {
                        "message": message,
                        "domain": "csebridge",
                        "reason": reason,
                    }
                ],
                "status": status or _status_for(code),
            }
        }


def _status_for(code):
    return {
        400: "INVALID_ARGUMENT",
        401: "UNAUTHENTICATED",
        403: "PERMISSION_DENIED",
        404: "NOT_FOUND",
        429: "RESOURCE_EXHAUSTED",
    }.get(int(code), "INTERNAL")
