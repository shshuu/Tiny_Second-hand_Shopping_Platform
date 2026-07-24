from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("market", "0009_automoderationcase_reviewing")]
    operations = [migrations.RemoveConstraint(model_name="automoderationcase", name="unique_auto_moderation_target")]
