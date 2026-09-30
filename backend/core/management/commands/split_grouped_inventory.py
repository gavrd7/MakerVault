from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from core.models import BOMAllocation, InventoryHistory, InventoryItem


PREFIXES = {
    "board": "MCU",
    "component": "CMP",
    "tool": "AST",
    "printed_part": "PRT",
    "other": "OTH",
}


def next_inventory_id(owner, item_type):
    prefix = PREFIXES.get(item_type, "INV")
    highest = 0
    for existing in InventoryItem.objects.filter(
        owner=owner,
        inventory_id__startswith=f"{prefix}-",
    ).values_list("inventory_id", flat=True):
        parts = str(existing or "").split("-")
        if len(parts) == 2 and parts[0] == prefix and parts[1].isdigit():
            highest = max(highest, int(parts[1]))
    candidate = highest + 1
    while InventoryItem.objects.filter(
        owner=owner,
        inventory_id=f"{prefix}-{candidate:04d}",
    ).exists():
        candidate += 1
    return f"{prefix}-{candidate:04d}"


class Command(BaseCommand):
    help = "Split legacy grouped inventory quantities into one record per physical unit."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the split. Without this flag the command only reports what would change.",
        )

    def handle(self, *args, **options):
        grouped = list(
            InventoryItem.objects.filter(quantity__gt=1)
            .select_related("owner", "board", "component", "project")
            .order_by("owner_id", "inventory_id")
        )
        if not grouped:
            self.stdout.write(self.style.SUCCESS("No grouped inventory records found."))
            return

        splittable = []
        skipped = []
        for item in grouped:
            quantity = Decimal(item.quantity)
            if quantity != quantity.to_integral_value():
                skipped.append((item, f"non-integer quantity {quantity}"))
                continue
            allocations = list(item.bom_allocations.select_related("bom_item", "allocated_by").all())
            if any(Decimal(a.quantity) != Decimal(a.quantity).to_integral_value() for a in allocations):
                skipped.append((item, "contains a fractional BOM allocation"))
                continue
            allocated = sum((Decimal(a.quantity) for a in allocations), Decimal("0"))
            if allocated > quantity:
                skipped.append((item, f"allocated quantity {allocated} exceeds total {quantity}"))
                continue
            splittable.append((item, int(quantity), allocations))

        self.stdout.write(
            f"Grouped inventory: {len(grouped)} found, {len(splittable)} splittable, {len(skipped)} skipped."
        )
        for item, count, _allocations in splittable[:50]:
            self.stdout.write(f"  split {item.inventory_id} · {item.display_name}: {count} units")
        for item, reason in skipped[:50]:
            self.stdout.write(self.style.WARNING(f"  skip {item.inventory_id}: {reason}"))

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --apply to make changes."))
            return

        created_total = 0
        with transaction.atomic():
            for item, count, allocations in splittable:
                original_quantity = Decimal(item.quantity)
                item.quantity = Decimal("1")
                item.save(update_fields=["quantity", "updated_at"])

                units = [item]
                for _index in range(count - 1):
                    clone = InventoryItem.objects.create(
                        owner=item.owner,
                        inventory_id=next_inventory_id(item.owner, item.item_type),
                        item_type=item.item_type,
                        board=item.board,
                        component=item.component,
                        custom_name=item.custom_name,
                        quantity=Decimal("1"),
                        status=item.status,
                        project=item.project,
                        location=item.location,
                        serial_number="",
                        purchase_price=item.purchase_price,
                        currency=item.currency,
                        supplier=item.supplier,
                        purchase_url=item.purchase_url,
                        purchased_on=item.purchased_on,
                        image=item.image,
                        notes=item.notes,
                    )
                    InventoryHistory.objects.create(
                        inventory_item=clone,
                        event_type="created",
                        summary=f"Created by splitting grouped inventory record {item.inventory_id}",
                        changes={
                            "source_inventory_id": item.inventory_id,
                            "source_quantity": str(original_quantity),
                        },
                        project=clone.project,
                    )
                    units.append(clone)
                    created_total += 1

                unit_cursor = 0
                for allocation in allocations:
                    allocation_count = int(Decimal(allocation.quantity))
                    if allocation_count < 1:
                        continue
                    allocation.inventory_item = units[unit_cursor]
                    allocation.quantity = Decimal("1")
                    allocation.save(update_fields=["inventory_item", "quantity", "updated_at"])
                    unit_cursor += 1
                    for _index in range(allocation_count - 1):
                        BOMAllocation.objects.create(
                            bom_item=allocation.bom_item,
                            inventory_item=units[unit_cursor],
                            quantity=Decimal("1"),
                            notes=allocation.notes,
                            allocated_by=allocation.allocated_by,
                        )
                        unit_cursor += 1

                InventoryHistory.objects.create(
                    inventory_item=item,
                    event_type="updated",
                    summary=f"Split grouped quantity {original_quantity} into individual inventory units",
                    changes={
                        "quantity": {"from": str(original_quantity), "to": "1"},
                        "created_units": count - 1,
                    },
                    project=item.project,
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Split complete: {len(splittable)} grouped records normalised, {created_total} new inventory records created."
            )
        )
