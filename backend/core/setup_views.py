from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.clickjacking import xframe_options_deny

from .first_run import InitialAdminForm, establish_initial_admin, needs_setup


@never_cache
@csrf_protect
@xframe_options_deny
def initial_setup(request):
    if not needs_setup():
        return redirect("/accounts/login/")
    if request.method == "POST":
        # Fixed window per remote address; generic errors avoid disclosing token validity.
        address = request.META.get("REMOTE_ADDR", "unknown")
        key = "first-run-attempts:" + __import__("hashlib").sha256(address.encode()).hexdigest()
        if cache.get(key, 0) >= 8:
            return render(request, "core/first_run.html", {"form": InitialAdminForm(), "rate_limited": True}, status=429)
        form = InitialAdminForm(request.POST)
        if form.is_valid():
            try:
                establish_initial_admin(form.cleaned_data)
            except ValueError:
                form.add_error("token", "Setup could not be completed. Check your token or create a new one.")
            else:
                cache.delete(key)
                return redirect("/accounts/login/?setup=complete")
        if cache.add(key, 1, timeout=900) is False:
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, timeout=900)
    else:
        form = InitialAdminForm()
    return render(request, "core/first_run.html", {"form": form})
