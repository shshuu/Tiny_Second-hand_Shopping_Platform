# Generated for the operations review workflow.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("market", "0007_automoderationcase")]

    operations = [
        migrations.AddField(
            model_name="automoderationcase",
            name="assigned_to",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="assigned_auto_cases", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(model_name="automoderationcase", name="assignment_version", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="automoderationcase", name="started_at", field=models.DateTimeField(blank=True, null=True)),
    ]
