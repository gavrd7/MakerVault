from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_legacy_bom_allocations(apps, schema_editor):
    BOMItem = apps.get_model("core", "BOMItem")
    BOMAllocation = apps.get_model("core", "BOMAllocation")
    InventoryItem = apps.get_model("core", "InventoryItem")

    for bom_item in BOMItem.objects.all().iterator():
        changed = False
        if bom_item.quantity is None or bom_item.quantity <= 0:
            bom_item.quantity = 1
            changed = True
        if changed:
            bom_item.save(update_fields=["quantity"])

        if not bom_item.inventory_item_id:
            continue
        inventory = InventoryItem.objects.filter(pk=bom_item.inventory_item_id).first()
        if not inventory or inventory.quantity is None or inventory.quantity <= 0:
            continue
        allocation_quantity = min(bom_item.quantity, inventory.quantity)
        if allocation_quantity > 0:
            BOMAllocation.objects.get_or_create(
                bom_item_id=bom_item.pk,
                inventory_item_id=inventory.pk,
                defaults={"quantity": allocation_quantity},
            )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_cataloguemaintenancesettings"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BOMAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12)),
                ("notes", models.TextField(blank=True)),
                ("allocated_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="makervault_bom_allocations",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("bom_item", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="allocations",
                    to="core.bomitem",
                )),
                ("inventory_item", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="bom_allocations",
                    to="core.inventoryitem",
                )),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.RunPython(migrate_legacy_bom_allocations, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="bomitem",
            name="inventory_item",
        ),
        migrations.AlterField(
            model_name="inventoryhistory",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("created", "Added to inventory"),
                    ("updated", "Updated"),
                    ("assigned", "Assigned to project"),
                    ("unassigned", "Removed from project"),
                    ("status", "Status changed"),
                    ("location", "Location changed"),
                    ("bom_allocated", "Allocated to BOM"),
                    ("bom_released", "Released from BOM"),
                ],
                default="updated",
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="bomitem",
            constraint=models.CheckConstraint(
                condition=models.Q(("quantity__gt", 0)),
                name="bom_item_quantity_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="bomallocation",
            constraint=models.UniqueConstraint(
                fields=("bom_item", "inventory_item"),
                name="unique_bom_inventory_allocation",
            ),
        ),
        migrations.AddConstraint(
            model_name="bomallocation",
            constraint=models.CheckConstraint(
                condition=models.Q(("quantity__gt", 0)),
                name="bom_allocation_quantity_positive",
            ),
        ),
    ]
