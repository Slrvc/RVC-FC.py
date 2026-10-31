from __future__ import annotations

from typing import TYPE_CHECKING

from django.shortcuts import render

if TYPE_CHECKING:
    from django.http import HttpRequest


# Create your views here.
def home(request: HttpRequest):
    return render(request, "rvcfc/home.html", context={
        "title": "RVC-FC (Home)",
        "description": "Seja bem-vindo ao RVC-FC.",
        "name": "RVC FC"
    })
