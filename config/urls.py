from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path, re_path
from django.views.static import serve

# The project-facing operations UI is /operations/.  Django's model-admin is
# intentionally not exposed as a second management surface.
urlpatterns = [path("", include("market.urls"))]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif settings.SERVE_MEDIA_LOCALLY:
    # Explicit local-demo opt-in; Django's static() intentionally does not do
    # this with DEBUG=False. django.views.static.serve uses safe_join.
    urlpatterns += [re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT})]

handler400 = "market.views.error_400"
handler403 = "market.views.error_403"
handler404 = "market.views.error_404"
handler500 = "market.views.error_500"
