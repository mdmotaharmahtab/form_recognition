import logging
from logging.handlers import RotatingFileHandler

# Configure logging with RotatingFileHandler
log_handler = RotatingFileHandler('system.log', maxBytes=10*1048576, backupCount=5) #10MB
log_handler.setLevel(logging.INFO)  # Ensure this handler logs INFO and above

# Define the log format
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_handler.setFormatter(formatter)

# Get the root logger and set its level to INFO
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)  # Set the root logger to INFO level

# Add the handler to the root logger
logger.addHandler(log_handler)

