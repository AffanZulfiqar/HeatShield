"""Provider selection."""
from app import config
from app.providers.replay import ReplayProvider

_provider = None


def get_provider():
    """Live FortyGuard client only when a key is actually present; replay otherwise.
    This check is intentionally redundant with config.resolved_mode() so that a
    misconfigured .env (DATA_MODE=live but no key) never causes a crash at runtime.
    """
    global _provider
    if _provider is not None:
        return _provider

    if config.resolved_mode() == "live" and config._fg_key():
        from app.providers.fortyguard import FortyGuardProvider
        _provider = FortyGuardProvider()
    else:
        if config.resolved_mode() == "live" and not config._fg_key():
            import logging
            logging.getLogger("scorched").warning(
                "DATA_MODE=live but FORTYGUARD_API_KEY is not set — falling back to demo mode. "
                "Add your key to .env and restart to use live data."
            )
        _provider = ReplayProvider()
    return _provider


def reset_provider():
    global _provider
    _provider = None
