from django.db import migrations

TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION market_prevent_wallet_history_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'completed wallet history is immutable';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER market_transaction_immutable BEFORE UPDATE OR DELETE ON market_wallettransaction FOR EACH ROW EXECUTE FUNCTION market_prevent_wallet_history_mutation();
CREATE TRIGGER market_ledger_immutable BEFORE UPDATE OR DELETE ON market_ledgerentry FOR EACH ROW EXECUTE FUNCTION market_prevent_wallet_history_mutation();
"""
DROP_SQL = """
DROP TRIGGER IF EXISTS market_transaction_immutable ON market_wallettransaction;
DROP TRIGGER IF EXISTS market_ledger_immutable ON market_ledgerentry;
DROP FUNCTION IF EXISTS market_prevent_wallet_history_mutation();
"""
def apply(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql": schema_editor.execute(TRIGGER_SQL)
def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql": schema_editor.execute(DROP_SQL)
class Migration(migrations.Migration):
    dependencies=[("market","0001_initial")]
    operations=[migrations.RunPython(apply,reverse)]
