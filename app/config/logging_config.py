import logging

from app.config.settings import settings

logger = logging.getLogger("homidirect")


def _configure() -> None:
    if logger.handlers:
        return
    logger.setLevel(settings.log_level.upper())
    handler = logging.FileHandler(settings.log_file)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)


_configure()
