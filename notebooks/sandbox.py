from loguru import logger
from src.config import settings

logger.info(f"Current environment: {settings.env}")
logger.info(f"Debug mode: {settings.debug}")
logger.info(f"Base directory: {settings.base_dir}")
logger.info(f"Data directory: {settings.data_dir}")
logger.info(f"Django base directory: {settings.django_base_dir}")    


