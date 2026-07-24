from django.test import override_settings
from django.test.runner import DiscoverRunner


class IsolatedSettingsTestRunner(DiscoverRunner):
    """Keep test fixtures independent from a developer's `.env` promotion flag."""

    def setup_test_environment(self, **kwargs):
        self._welcome_bonus_override = override_settings(WELCOME_BONUS_ENABLED=False)
        self._welcome_bonus_override.enable()
        return super().setup_test_environment(**kwargs)

    def teardown_test_environment(self, **kwargs):
        try:
            return super().teardown_test_environment(**kwargs)
        finally:
            self._welcome_bonus_override.disable()
