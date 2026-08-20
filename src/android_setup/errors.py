class AndroidSetupError(Exception):
    """Base error for expected, user-facing failures."""


class ConfigError(AndroidSetupError):
    """Profile or secret configuration is invalid."""


class ProviderError(AndroidSetupError):
    """An artifact provider could not resolve a download."""


class ValidationError(AndroidSetupError):
    """A downloaded artifact failed validation."""


class AdbError(AndroidSetupError):
    """ADB discovery or provisioning failed."""
