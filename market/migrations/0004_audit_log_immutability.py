from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("market", "0003_user_public_id_product_indexes")]
    operations = [migrations.RunSQL(
        """
        CREATE OR REPLACE FUNCTION market_block_audit_log_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Audit log is append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_audit_log_no_update BEFORE UPDATE ON market_auditlog FOR EACH ROW EXECUTE FUNCTION market_block_audit_log_mutation();
        CREATE TRIGGER market_audit_log_no_delete BEFORE DELETE ON market_auditlog FOR EACH ROW EXECUTE FUNCTION market_block_audit_log_mutation();
        """,
        """
        DROP TRIGGER IF EXISTS market_audit_log_no_update ON market_auditlog;
        DROP TRIGGER IF EXISTS market_audit_log_no_delete ON market_auditlog;
        DROP FUNCTION IF EXISTS market_block_audit_log_mutation();
        """,
    )]
