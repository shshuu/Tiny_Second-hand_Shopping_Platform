from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("market", "0004_audit_log_immutability")]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunSQL(
            "ALTER TABLE market_report ADD COLUMN IF NOT EXISTS assigned_to_id bigint NULL REFERENCES market_user(id) DEFERRABLE INITIALLY DEFERRED; ALTER TABLE market_report ADD COLUMN IF NOT EXISTS assignment_version integer NOT NULL DEFAULT 0;",
            "ALTER TABLE market_report DROP COLUMN IF EXISTS assignment_version; ALTER TABLE market_report DROP COLUMN IF EXISTS assigned_to_id;",
        )],
        state_operations=[
            migrations.AddField(model_name="report", name="assigned_to", field=models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="assigned_reports", to=settings.AUTH_USER_MODEL)),
            migrations.AddField(model_name="report", name="assignment_version", field=models.PositiveIntegerField(default=0)),
        ],
    )]
