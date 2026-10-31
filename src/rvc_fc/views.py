from __future__ import annotations

from typing import TYPE_CHECKING

from django.shortcuts import render

if TYPE_CHECKING:
    from django.http import HttpRequest


# Create your views here.
def home(request: HttpRequest):
    return render(request, "rvcfc/pages/home.html", context={
        "title": "RVC-FC (Home)",
        "description": "Controle de Produção | Florestal | Carvão",
        "name": "RVC-FC"
    })
