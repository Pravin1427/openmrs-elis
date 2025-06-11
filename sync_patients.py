import requests
import json
import base64
import logging
import threading
import time
from datetime import datetime

# --- PostgreSQL specific import ---
import psycopg2
from psycopg2 import sql
from psycopg2.extras import DictCursor # To fetch rows as dictionaries

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
# IMPORTANT: Customize these configurations for your environments
OPENMRS_CONFIG = {
    "base_url": "http://localhost/openmrs",
    "username": "admin",
    "password": "Admin123"
}

OPENELIS_CONFIG = {
    "base_url": "https://localhost:8445", # Make sure this matches your OpenELIS instance
    "username": "admin",
    "password": "adminADMIN!"
}

POSTGRES_CONFIG = {
    "host": "localhost",
    "database": "sync_db",       # <--- CHANGE THIS: Your PostgreSQL database name
    "user": "sync_user",         # <--- CHANGE THIS: Your PostgreSQL username
    "password": "prabin1234", # <--- CHANGE THIS: Your PostgreSQL password
    "port": 5432                 # Default PostgreSQL port
}

# --- Integration Classes (Reused with minor adjustments) ---

class OpenMRSIntegration:
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.jsessionid = None
        # Ensure these UUIDs are correct for your OpenMRS instance
        self.location_uuid = "ba685651-ed3b-4e63-9b35-78893060758a"
        self.identifier_source_uuid = "8549f706-7e85-4c1d-9424-217d50a2988b"

    def _get_auth_header(self):
        auth_string = f"{self.username}:{self.password}"
        encoded_auth = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
        return {"Authorization": f"Basic {encoded_auth}"}

    def login(self):
        logging.info("Attempting to log in to OpenMRS...")
        headers = self._get_auth_header()
        
        try:
            response = self.session.get(f"{self.base_url}/ws/rest/v1/session", headers=headers, verify=False, timeout=10)
            response.raise_for_status()
            
            if 'JSESSIONID' in self.session.cookies:
                self.jsessionid = self.session.cookies['JSESSIONID']
                logging.debug(f"OpenMRS JSESSIONID obtained: {self.jsessionid}")
            else:
                logging.error("OpenMRS JSESSIONID not found in initial session GET.")
                return False

            session_data = response.json()
            if session_data.get('authenticated'):
                logging.info("OpenMRS initial session GET successful. Setting session location...")
                
                post_headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
                post_payload = {"sessionLocation": self.location_uuid}
                post_response = self.session.post(
                    f"{self.base_url}/ws/rest/v1/session", 
                    headers=post_headers, 
                    data=json.dumps(post_payload),
                    verify=False,
                    timeout=10
                )
                post_response.raise_for_status()
                post_session_data = post_response.json()
                if post_session_data.get('authenticated') and post_session_data.get('sessionLocation'):
                    logging.info("OpenMRS session location set successfully. Login complete.")
                    return True
                else:
                    logging.error("Failed to set OpenMRS session location or not authenticated after POST.")
                    return False
            else:
                logging.error("OpenMRS authentication failed during initial session GET.")
                return False
        except requests.exceptions.Timeout:
            logging.error("OpenMRS login failed: Request timed out.")
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"OpenMRS login failed: {e}")
            return False

    def get_syncer_records(self):
        logging.info("Fetching syncer records from OpenMRS syncerrecord endpoint with pagination support...")
        headers = self._get_auth_header()

        records = []
        next_url = f"{self.base_url}/ws/rest/v1/syncerrecord"

        try:
            while next_url:
                response = self.session.get(next_url, headers=headers, verify=False, timeout=30)
                response.raise_for_status()
            
                syncer_data = response.json()
                page_results = syncer_data.get('results', [])
                records.extend(page_results)
                logging.debug(f"Fetched {len(page_results)} records. Total so far: {len(records)}")
            
                # Check for next link in results
                next_url = None
                links = syncer_data.get('links', [])
                for link in links:
                    if link.get('rel') == 'next':
                        next_url = link.get('uri')
                        break
                    
            logging.info(f"Completed fetching all syncer records. Total count: {len(records)}")
            return records
        except requests.exceptions.Timeout:
            logging.error("Fetching syncer records failed: Request timed out.")
            return []
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch syncer records: {e}")
            return []

class OpenELISIntegration:
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.jsessionid = None
        self.csrf_token = None

    def login(self):
        logging.info("Attempting to log in to OpenELIS...")
        
        login_url = f"{self.base_url}/api/OpenELIS-Global/ValidateLogin?apiCall=true"
        login_payload = {
            "loginName": self.username,
            "password": self.password,
        }
        login_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*"
        }

        try:
            logging.info("Sending OpenELIS login POST request...")
            response = self.session.post(
                login_url, 
                headers=login_headers, 
                data=login_payload, 
                verify=False,
                timeout=10
            )
            response.raise_for_status()
            
            if 'JSESSIONID' in self.session.cookies:
                self.jsessionid = self.session.cookies['JSESSIONID']
                logging.debug(f"OpenELIS JSESSIONID obtained from login POST: {self.jsessionid}")
            else:
                logging.error("OpenELIS JSESSIONID not found after login POST.")
                return False

            logging.info("OpenELIS login POST successful. Now fetching CSRF token...")

            session_get_url = f"{self.base_url}/api/OpenELIS-Global/session"
            session_get_headers = {
                "Accept": "*/*",
            }
            session_response = self.session.get(session_get_url, headers=session_get_headers, verify=False, timeout=10)
            session_response.raise_for_status()
            
            session_data = session_response.json()
            if session_data.get('authenticated'):
                self.csrf_token = session_data.get('csrf')
                if self.csrf_token:
                    logging.debug(f"OpenELIS CSRF token obtained: {self.csrf_token}")
                    logging.info("OpenELIS session successfully established.")
                    return True
                else:
                    logging.error("Failed to retrieve OpenELIS CSRF token from session response.")
                    return False
            else:
                logging.error("OpenELIS session GET indicates not authenticated after login POST.")
                return False

        except requests.exceptions.Timeout:
            logging.error("OpenELIS login failed: Request timed out.")
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"OpenELIS login failed: {e}")
            logging.error(f"Response content: {e.response.text if e.response else 'No response'}")
            return False

    def create_openelis_patient(self, patient_data):
        logging.info("Creating patient in OpenELIS...")
        if not self.jsessionid or not self.csrf_token:
            logging.error("OpenELIS session or CSRF token not established. Please login first.")
            return False

        headers = {
            "Content-Type": "application/json",
            "X-CSRF-TOKEN": self.csrf_token,
            "Accept": "*/*"
        }
        try:
            response = self.session.post(
                f"{self.base_url}/api/OpenELIS-Global/rest/PatientManagement",
                headers=headers,
                data=json.dumps(patient_data),
                verify=False,
                timeout=20 # Increased timeout for patient creation
            )
            response.raise_for_status()
            logging.info("Patient creation request sent to OpenELIS. Status Code: 200 OK.")
            return True
        except requests.exceptions.HTTPError as e:
            logging.error(f"Failed to create patient in OpenELIS. HTTP Error: {e.response.status_code} - {e.response.text}")
            return False
        except requests.exceptions.Timeout:
            logging.error("Creating patient in OpenELIS failed: Request timed out.")
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to create patient in OpenELIS: {e}")
            return False

# --- Database Manager for Queue (PostgreSQL - NEW) ---

class DatabaseManager:
    def __init__(self, db_config):
        self.db_config = db_config
        self.conn = None
        self._connect()
        self._create_table()

    def _connect(self):
        try:
            # Connect to PostgreSQL using parameters from db_config
            self.conn = psycopg2.connect(**self.db_config)
            logging.info(f"Connected to PostgreSQL database: {self.db_config['database']}")
        except psycopg2.Error as e:
            logging.error(f"Failed to connect to PostgreSQL database: {e}")
            raise # Re-raise the exception to stop the application if DB connection fails

    def _create_table(self):
        cursor = self.conn.cursor()
        try:
            # PostgreSQL-specific SQL for table creation
            cursor.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS sync_queue (
                    uuid TEXT PRIMARY KEY, -- OpenMRS Syncer Record UUID
                    patient_data_json TEXT NOT NULL,
                    status TEXT NOT NULL, -- PENDING, PROCESSING, SUCCESS, FAILED, RETRYING
                    retries INTEGER DEFAULT 0,
                    last_attempt_time TIMESTAMP WITH TIME ZONE, -- Store timestamps with timezone info
                    error_message TEXT
                );
            """))
            self.conn.commit() # Commit the table creation
            logging.info("Sync queue database table ensured.")
        except psycopg2.Error as e:
            self.conn.rollback() # Rollback on error
            logging.error(f"Error creating sync_queue table: {e}")
            raise
        finally:
            cursor.close()

    def add_record(self, uuid, patient_data_json):
        cursor = self.conn.cursor()
        try:
            # ON CONFLICT DO NOTHING is a PostgreSQL feature for UPSERT/IGNORE
            cursor.execute(sql.SQL("""
                INSERT INTO sync_queue (uuid, patient_data_json, status, retries)
                VALUES (%s, %s, 'PENDING', 0)
                ON CONFLICT (uuid) DO NOTHING;
            """), (uuid, patient_data_json))
            if cursor.rowcount > 0: # rowcount > 0 means an insert occurred
                self.conn.commit()
                logging.debug(f"Added new record to queue: {uuid}")
                return True
            else:
                logging.debug(f"Record with UUID {uuid} already exists in queue. Skipping.")
                return False
        except psycopg2.Error as e:
            self.conn.rollback() # Rollback on error
            logging.error(f"Database error adding record {uuid}: {e}")
            return False
        finally:
            cursor.close()

    def get_pending_records(self, limit=10):
        # Use DictCursor to fetch rows as dictionaries
        cursor = self.conn.cursor(cursor_factory=DictCursor)
        try:
            # PostgreSQL-specific date/time calculation for cool-off
            # EXTRACT(EPOCH FROM (NOW() - last_attempt_time)) gives seconds difference
            cursor.execute(sql.SQL("""
                SELECT uuid, patient_data_json, status, retries, last_attempt_time, error_message
                FROM sync_queue
                WHERE status IN ('PENDING', 'RETRYING')
                AND (
                    last_attempt_time IS NULL 
                    OR (EXTRACT(EPOCH FROM (NOW() - last_attempt_time))) > (retries * 30) -- Exponential backoff (30s * retries)
                )
                ORDER BY last_attempt_time ASC NULLS FIRST, retries ASC
                LIMIT %s;
            """), (limit,))
            records = cursor.fetchall()
            return records
        except psycopg2.Error as e:
            logging.error(f"Database error fetching pending records: {e}")
            return []
        finally:
            cursor.close()

    def mark_as_processing(self, uuid):
        cursor = self.conn.cursor()
        try:
            # Use datetime.utcnow() for TIMESTAMP WITH TIME ZONE
            now_utc = datetime.utcnow() 
            cursor.execute(sql.SQL("""
                UPDATE sync_queue SET status = 'PROCESSING', last_attempt_time = %s
                WHERE uuid = %s;
            """), (now_utc, uuid))
            self.conn.commit()
        except psycopg2.Error as e:
            self.conn.rollback() # Rollback on error
            logging.error(f"Database error marking record {uuid} as processing: {e}")
        finally:
            cursor.close()

    def update_record_status(self, uuid, status, error_message=None):
        cursor = self.conn.cursor()
        try:
            now_utc = datetime.utcnow()
            if status == 'SUCCESS':
                cursor.execute(sql.SQL("""
                    UPDATE sync_queue SET status = %s, error_message = NULL, last_attempt_time = %s
                    WHERE uuid = %s;
                """), (status, now_utc, uuid))
            else: # FAILED or RETRYING
                cursor.execute(sql.SQL("""
                    UPDATE sync_queue SET status = %s, error_message = %s, retries = retries + 1, last_attempt_time = %s
                    WHERE uuid = %s;
                """), (status, error_message, now_utc, uuid))
            self.conn.commit()
            logging.debug(f"Record {uuid} status updated to {status}. Error: {error_message}")
        except psycopg2.Error as e:
            self.conn.rollback() # Rollback on error
            logging.error(f"Database error updating status for record {uuid}: {e}")
        finally:
            cursor.close()

    def close(self):
        if self.conn:
            self.conn.close()
            logging.info("PostgreSQL database connection closed.")

# --- Patient Middleware (Modified Constructor) ---

class PatientMiddleware:
    def __init__(self, openmrs_instance, openelis_instance):
        # PatientMiddleware now directly takes instances of the integration classes
        self.openmrs = openmrs_instance
        self.openelis = openelis_instance

    def synchronize_single_syncer_record_to_openelis(self, syncer_record_data):
        logging.info(f"Attempting to synchronize syncer record '{syncer_record_data.get('patientIdentifier')}' to OpenELIS.")

        # The QueueProcessor will handle OpenELIS login before calling this method,
        # but a local check for robustness is still good.
        if not self.openelis.jsessionid or not self.openelis.csrf_token:
            if not self.openelis.login():
                logging.error("Failed to log in to OpenELIS or retrieve CSRF token. Aborting synchronization for this record.")
                return False

        patient_id = syncer_record_data.get('patientIdentifier', '')
        first_name = syncer_record_data.get('givenName', '')
        last_name = syncer_record_data.get('familyName', '')
        gender = syncer_record_data.get('gender', '')
        birthdate_openmrs = syncer_record_data.get('birthdate', '')
        
        # --- Data Transformation Logic (As per your original script) ---
        birthdate_elis = ""
        if birthdate_openmrs:
            try:
                if 'T' in birthdate_openmrs:
                    dt_object = datetime.fromisoformat(birthdate_openmrs.replace('Z', '+00:00'))
                else:
                    dt_object = datetime.strptime(birthdate_openmrs, "%Y-%m-%d")
                birthdate_elis = dt_object.strftime("%d/%m/%Y")
            except ValueError:
                logging.warning(f"Could not parse birthdate '{birthdate_openmrs}' from syncer record. Using empty string for OpenELIS.")
        
        openelis_patient_payload = {
            "patientUpdateStatus": "ADD", 
            "nationalId": patient_id,
            "subjectNumber": patient_id,
            "lastName": last_name,
            "firstName": first_name,
            "gender": gender,
            "birthDateForDisplay": birthdate_elis,
            "primaryPhone": "", 
            "streetAddress": "", 
            "city": "",
            "commune": "",  
            "education": "",  
            "healthDistrict": "",  
            "healthRegion": "",  
            "maritialStatus": "",  
            "nationality": "",  
            "otherNationality": "",  
            "patientContact": {  
                "person": {
                    "firstName": "",  
                    "lastName": "",
                    "primaryPhone": "",
                    "email": ""
                }
            }
        }
        logging.debug(f"Transformed syncer record data for OpenELIS: {json.dumps(openelis_patient_payload, indent=2)}")

        if self.openelis.create_openelis_patient(openelis_patient_payload):
            logging.info(f"Syncer record '{patient_id}' successfully synchronized to OpenELIS.")
            return True
        else:
            logging.error(f"Failed to synchronize syncer record '{patient_id}' to OpenELIS.")
            return False

# --- Operational Components (Threads - Reused Logic) ---

class SourceDataPoller(threading.Thread):
    def __init__(self, openmrs_integration, db_manager, polling_interval_seconds=60):
        super().__init__()
        self.openmrs = openmrs_integration
        self.db_manager = db_manager
        self.polling_interval = polling_interval_seconds
        self._stop_event = threading.Event() # Used for graceful shutdown
        logging.info(f"SourceDataPoller initialized with polling interval: {self.polling_interval} seconds.")

    def run(self):
        logging.info("SourceDataPoller started.")
        while not self._stop_event.is_set(): # Loop until stop event is set
            if not self.openmrs.jsessionid:
                logging.warning("Poller: OpenMRS session not active. Attempting login...")
                if not self.openmrs.login():
                    logging.error("Poller: Failed to log in to OpenMRS. Retrying login in 30 seconds.")
                    self._stop_event.wait(30) # Wait before re-attempting login
                    continue # Skip to next loop iteration

            logging.info("Poller: Fetching syncer records from OpenMRS...")
            syncer_records = self.openmrs.get_syncer_records()
            
            if syncer_records:
                logging.info(f"Poller: Found {len(syncer_records)} records from syncerrecord. Adding to queue...")
                for record in syncer_records:
                    record_uuid = record.get('patientIdentifier') # Assuming syncer records have a 'uuid'
                    if not record_uuid:
                        logging.warning(f"Syncer record missing UUID, skipping: {json.dumps(record)}")
                        continue
                    # Add to database queue. DatabaseManager handles de-duplication with ON CONFLICT.
                    self.db_manager.add_record(record_uuid, json.dumps(record))
            else:
                logging.info("Poller: No new syncer records found or an error occurred during fetch.")
            
            self._stop_event.wait(self.polling_interval) # Wait for next polling interval
        logging.info("SourceDataPoller stopped.")

    def stop(self):
        self._stop_event.set() # Signal the thread to stop

class QueueProcessor(threading.Thread):
    def __init__(self, db_manager, patient_middleware, processing_interval_seconds=5, max_retries=5):
        super().__init__()
        self.db_manager = db_manager
        self.patient_middleware = patient_middleware
        self.processing_interval = processing_interval_seconds
        self.max_retries = max_retries
        self._stop_event = threading.Event() # Used for graceful shutdown
        logging.info(f"QueueProcessor initialized with processing interval: {self.processing_interval} seconds, max retries: {self.max_retries}.")

    def run(self):
        logging.info("QueueProcessor started.")
        while not self._stop_event.is_set(): # Loop until stop event is set
            # Ensure OpenELIS is logged in before attempting to process
            if not self.patient_middleware.openelis.jsessionid or not self.patient_middleware.openelis.csrf_token:
                logging.warning("Processor: OpenELIS session not active. Attempting login...")
                if not self.patient_middleware.openelis.login():
                    logging.error("Processor: Failed to log in to OpenELIS. Cannot process records. Retrying login in 10 seconds.")
                    self._stop_event.wait(10) # Wait before re-attempting login
                    continue # Skip to next loop iteration

            records_to_process = self.db_manager.get_pending_records(limit=10) # Process records in batches
            if records_to_process:
                logging.info(f"Processor: Found {len(records_to_process)} records to process from queue.")
                for record_row in records_to_process:
                    uuid = record_row['uuid']
                    patient_data_json = record_row['patient_data_json']
                    current_retries = record_row['retries']

                    if current_retries >= self.max_retries:
                        self.db_manager.update_record_status(uuid, 'FAILED', "Exceeded max retries.")
                        logging.error(f"Processor: Record {uuid} exceeded max retries ({self.max_retries}). Marked as FAILED.")
                        continue # Move to the next record

                    try:
                        self.db_manager.mark_as_processing(uuid) # Mark as processing immediately
                        patient_data = json.loads(patient_data_json)
                        logging.info(f"Processor: Attempting to synchronize record {uuid} (attempt {current_retries + 1})...")
                        
                        success = self.patient_middleware.synchronize_single_syncer_record_to_openelis(patient_data)
                        
                        if success:
                            self.db_manager.update_record_status(uuid, 'SUCCESS')
                            logging.info(f"Processor: Successfully synchronized record {uuid}.")
                        else:
                            error_msg = f"Synchronization failed for record {uuid}."
                            self.db_manager.update_record_status(uuid, 'RETRYING', error_msg)
                            logging.warning(f"Processor: {error_msg} Retrying later.")
                    except json.JSONDecodeError as e:
                        error_msg = f"Invalid JSON data in record {uuid}: {e}"
                        self.db_manager.update_record_status(uuid, 'FAILED', error_msg)
                        logging.error(f"Processor: {error_msg}")
                    except Exception as e: # Catch any other unexpected errors during processing
                        error_msg = f"Unexpected error processing record {uuid}: {e}"
                        self.db_manager.update_record_status(uuid, 'RETRYING', error_msg)
                        logging.error(f"Processor: {error_msg}. Retrying later.")
            else:
                logging.debug("Processor: No records to process.")
            
            self._stop_event.wait(self.processing_interval) # Wait for next processing interval
        logging.info("QueueProcessor stopped.")

    def stop(self):
        self._stop_event.set() # Signal the thread to stop

# --- Main Application Entry Point ---

def main_automated():
    logging.info("Starting synchronization service...")
    
    # 1. Initialize Database Manager (using PostgreSQL config)
    try:
        db_manager = DatabaseManager(POSTGRES_CONFIG)
    except Exception as e:
        logging.critical(f"Failed to initialize DatabaseManager: {e}. Exiting.")
        return

    # 2. Initialize Integration Classes
    openmrs_integration = OpenMRSIntegration(**OPENMRS_CONFIG)
    openelis_integration = OpenELISIntegration(**OPENELIS_CONFIG)
    
    # 3. Initialize Patient Middleware with the integration instances
    patient_middleware = PatientMiddleware(openmrs_integration, openelis_integration)

    # 4. Initialize Poller and Processor threads
    poller = SourceDataPoller(openmrs_integration, db_manager, polling_interval_seconds=60) # Poll OpenMRS every 60 seconds
    processor = QueueProcessor(db_manager, patient_middleware, processing_interval_seconds=5, max_retries=5) # Process queue every 5 seconds, up to 5 retries

    # 5. Start the threads
    poller.start()
    processor.start()

    logging.info("Synchronization service threads started. Press Ctrl+C to stop.")

    try:
        # Keep the main thread alive. This will catch Ctrl+C for graceful shutdown.
        while True:
            time.sleep(1) 
    except KeyboardInterrupt:
        logging.info("Shutdown signal received. Stopping services gracefully...")
        poller.stop()      # Signal poller to stop
        processor.stop()   # Signal processor to stop
        poller.join()      # Wait for poller thread to finish its current cycle
        processor.join()   # Wait for processor thread to finish its current cycle
        db_manager.close() # Close the database connection
        logging.info("Services stopped. Exiting.")

# --- Script Execution ---

if __name__ == "__main__":
    # Disable SSL warnings for local development (use with caution in production)
    requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    
    # Run the automated synchronization service
    main_automated()