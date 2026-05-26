from django.http import HttpResponse
from django.template.loader import render_to_string


def _render_error_template(template_name, status_code):
    content = render_to_string(template_name, {})
    return HttpResponse(content, status=status_code)


def handler400(request, exception):
    return _render_error_template("400.html", 400)


def handler403(request, exception):
    return _render_error_template("403.html", 403)


def handler404(request, exception):
    return _render_error_template("404.html", 404)


def handler500(request):
    return _render_error_template("500.html", 500)


def csrf_failure(request, reason="", template_name="403.html"):
    return _render_error_template(template_name, 403)
