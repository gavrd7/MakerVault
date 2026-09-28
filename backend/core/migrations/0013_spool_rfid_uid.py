from django.db import migrations, models


def seed_unambiguous_legacy_spool_rfids(apps, schema_editor):
    Spool = apps.get_model("core", "Spool")
    PrinterFilamentSlot = apps.get_model("core", "PrinterFilamentSlot")

    claimed = set()
    for spool in Spool.objects.select_related("filament").all():
        filament_color = str(spool.filament.color_hex or "").strip().lower()
        if not filament_color:
            continue

        matching_tags = set()
        slots = PrinterFilamentSlot.objects.filter(
            spool_id=spool.pk,
            is_loaded=True,
        )
        for slot in slots:
            slot_color = str(slot.color_hex or "").strip().lower()
            if not slot_color or slot_color != filament_color:
                continue
            metadata = slot.metadata or {}
            raw_tag = (
                slot.rfid_uid
                or metadata.get("rfid_uid")
                or metadata.get("material_code")
                or ""
            )
            tag = str(raw_tag).strip().upper()
            if tag:
                matching_tags.add(tag)

        if len(matching_tags) != 1:
            continue
        tag = next(iter(matching_tags))
        if tag in claimed:
            continue
        if Spool.objects.exclude(pk=spool.pk).filter(rfid_uid=tag).exists():
            continue
        spool.rfid_uid = tag
        spool.save(update_fields=["rfid_uid"])
        claimed.add(tag)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_printing_integration_sync_schedule"),
    ]

    operations = [
        migrations.AddField(
            model_name="spool",
            name="rfid_uid",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.RunPython(
            seed_unambiguous_legacy_spool_rfids,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="spool",
            constraint=models.UniqueConstraint(
                condition=~models.Q(rfid_uid=""),
                fields=("rfid_uid",),
                name="unique_nonblank_spool_rfid_uid",
            ),
        ),
    ]
