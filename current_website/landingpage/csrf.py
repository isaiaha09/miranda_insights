from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.template.loader import render_to_string


def csrf_failure(request, reason=""):
	details = {
		"reason": reason or "CSRF verification failed.",
		"path": request.path,
		"method": request.method,
	}

	if settings.DEBUG:
		details.update(
			{
				"has_csrf_cookie": bool(request.COOKIES.get("csrftoken")),
				"csrf_cookie_length": len(request.COOKIES.get("csrftoken", "")),
				"form_token_length": len((request.POST.get("csrfmiddlewaretoken") or "")),
				"header_token_length": len((request.META.get("HTTP_X_CSRFTOKEN") or "")),
			}
		)

	if request.headers.get("x-requested-with") == "XMLHttpRequest":
		return JsonResponse({"error": "CSRF verification failed", "details": details}, status=403)

	html = render_to_string("403_csrf.html", {"details": details, "show_debug": settings.DEBUG}, request=request)
	return HttpResponseForbidden(html)