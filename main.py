# main.py

import requests
import logging
import threading
import time
import os

# Import classes from your new files
from database import DatabaseManager
from openmrs_integration import OpenMRSIntegration
from openelis_integration import OpenELISIntegration
from patient_middleware import PatientMiddleware
from poller_and_processor import OpenMRSPatientPoller, QueueProcessor

# Configure global logging for the entire application
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# Set a higher level for 'requests' and 'urllib3' to reduce verbosity from their debug logs
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

# --- CONFIGURATION ---
OPENMRS_CONFIG = {
    "base_url": "http://localhost/openmrs",
    "username": "admin",
    "password": "Admin123",
    "location_uuid": "ba685651-ed3b-4e63-9b35-78893060758a" # Your specific location UUID
}

OPENELIS_CONFIG = {
    "base_url": "https://localhost:8445",
    "username": "admin",
    "password": "adminADMIN!"
}

POSTGRES_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "openmrs_openelis_sync",
    "user": "sync_user",
    "password": "prabin"
}

# Poller Specific Configuration
LAST_POLL_TIMESTAMP_FILE = "last_poll_timestamp.txt"
POLLING_INTERVAL_SEC = 15 # Shorter for testing, change to 300 (5 mins) for production
EVENT_FETCH_LIMIT = 100 # Number of event records to fetch per API call

# Queue Processor Specific Configuration
PROCESSING_INTERVAL_SEC = 15
MAX_RETRY_ATTEMPTS = 3
RETRY_COOL_OFF_MINUTES = 10 

def main():
    logging.info("Starting OpenMRS-OpenELIS Synchronization Service.")

    # Log current working directory for debugging file paths
    current_working_directory = os.getcwd()
    logging.info(f"Script is running in directory: {current_working_directory}")

    # Initialize and connect to the database
    db_manager = DatabaseManager(POSTGRES_CONFIG)
    if not db_manager.connect():
        logging.critical("Failed to connect to PostgreSQL. Exiting.")
        return
    if not db_manager.create_tables():
        logging.critical("Failed to create necessary database tables. Exiting.")
        db_manager.disconnect()
        return
    logging.info("Database initialized successfully.")
    
    # Initialize OpenMRS and OpenELIS integrations
    openmrs_integration = OpenMRSIntegration(**OPENMRS_CONFIG)
    openelis_integration = OpenELISIntegration(**OPENELIS_CONFIG)

    # Perform initial logins for both systems before starting threads
    # The poller and processor will re-login if sessions expire, but initial check is good
    if not openmrs_integration.login():
        logging.critical("Initial authentication with OpenMRS failed. Exiting.")
        db_manager.disconnect()
        return
    logging.info("Successfully authenticated with OpenMRS.")

    if not openelis_integration.login():
        logging.critical("Initial authentication with OpenELIS failed. Exiting.")
        db_manager.disconnect()
        return
    logging.info("Successfully authenticated with OpenELIS.")

    # Initialize Patient Middleware
    patient_middleware = PatientMiddleware(openmrs_integration, openelis_integration)
    
    # Initialize Poller and Queue Processor
    openmrs_poller = OpenMRSPatientPoller(
        openmrs_integration,
        db_manager,
        LAST_POLL_TIMESTAMP_FILE,
        POLLING_INTERVAL_SEC,
        EVENT_FETCH_LIMIT # Pass the renamed limit for event records
    )
    queue_processor = QueueProcessor(
        patient_middleware,
        db_manager,
        PROCESSING_INTERVAL_SEC,
        MAX_RETRY_ATTEMPTS,
        RETRY_COOL_OFF_MINUTES
    )

    logging.info("Starting OpenMRS Patient Poller and Queue Processor threads...")

    # Start threads
    poller_thread = threading.Thread(target=openmrs_poller.run, daemon=True, name="OpenMRSPollerThread")
    processor_thread = threading.Thread(target=queue_processor.run_processor, daemon=True, name="QueueProcessorThread")

    poller_thread.start()
    processor_thread.start()
    
    logging.info("Synchronization service is running. Press Ctrl+C to stop.")

    try:
        # Keep the main thread alive indefinitely
        while True:
            time.sleep(1) 
    except KeyboardInterrupt:
        logging.info("Shutdown signal received. Exiting synchronization service gracefully.")
    except Exception as e:
        logging.exception(f"An unexpected error occurred in the main thread: {e}")
    finally:
        # Ensure database connection is closed on exit
        db_manager.disconnect()
        logging.info("Database connection closed.")
        logging.info("Synchronization service terminated.")
    

if __name__ == "__main__":
    # Disable insecure request warnings globally for development
    # IMPORTANT: In production, use valid SSL certificates and remove verify=False
    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    main()