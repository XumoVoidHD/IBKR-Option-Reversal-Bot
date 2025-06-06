import logging
import os
from datetime import datetime

def setup_logger(name="Logger"):
    # Get current date and time
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M-%S")

    # Folder path relative to this file
    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, "logs", date_str)
    os.makedirs(log_dir, exist_ok=True)

    # Full log file path
    log_filename = os.path.join(log_dir, f"{date_str}_{time_str}.log")

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers
    if not logger.handlers:
        # File handler
        file_handler = logging.FileHandler(log_filename)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        ))

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(
            "%(levelname)s | %(message)s"
        ))

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger
