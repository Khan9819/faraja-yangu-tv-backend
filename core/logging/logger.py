import logging
from .formatter import SimpleFormatter

logger = logging.getLogger('app_logger')
handler = logging.StreamHandler()
handler.setFormatter(SimpleFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)
