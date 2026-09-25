from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .models import BoardModel, ComponentModel, FilamentProduct, InventoryItem, Project, Spool, Printer, Model3D


@login_required
def dashboard(request):
    data = {
        "inventory_total": InventoryItem.objects.count(),
        "inventory_available": InventoryItem.objects.filter(status="available").count(),
        "inventory_in_use": InventoryItem.objects.filter(status="in_use").count(),
        "projects_active": Project.objects.filter(status="active").count(),
        "projects_total": Project.objects.count(),
        "board_models": BoardModel.objects.count(),
        "component_models": ComponentModel.objects.count(),
        "filament_products": FilamentProduct.objects.count(),
        "spools": Spool.objects.count(),
        "printers": Printer.objects.count(),
        "models_3d": Model3D.objects.count(),
    }
    return JsonResponse(data)


@login_required
def inventory(request):
    rows = []
    qs = InventoryItem.objects.select_related("board__manufacturer", "component__manufacturer", "project").all()[:2000]
    for item in qs:
        image_url = None
        if item.image:
            image_url = item.image.url
        elif item.board and item.board.image:
            image_url = item.board.image.url
        elif item.component and item.component.image:
            image_url = item.component.image.url
        rows.append({
            "id": str(item.id),
            "inventory_id": item.inventory_id,
            "type": item.get_item_type_display(),
            "name": item.display_name,
            "quantity": float(item.quantity),
            "status": item.get_status_display(),
            "project": item.project.name if item.project else "",
            "location": item.location,
            "purchase_price": float(item.purchase_price) if item.purchase_price is not None else None,
            "currency": item.currency,
            "image": image_url,
        })
    return JsonResponse({"rows": rows})


@login_required
def public_config(request):
    return JsonResponse({
        "currency": settings.MAKERVAULT_CURRENCY,
        "measurement_system": settings.MAKERVAULT_MEASUREMENT_SYSTEM,
        "timezone": settings.TIME_ZONE,
        "language": settings.LANGUAGE_CODE,
        "user": request.user.get_username(),
        "is_staff": request.user.is_staff,
    })
