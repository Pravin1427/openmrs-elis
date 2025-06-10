# --- poller_and_processor.py (Temporary Debugging Change) ---

import logging
import time
from datetime import datetime, timezone, timedelta
import os
import json # Ensure json is imported
import re 

from openmrs_integration import OpenMRSIntegration
from openelis_integration import OpenELISIntegration
from patient_middleware import PatientMiddleware

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class OpenMRSPatientPoller:
    def __init__(self, openmrs_integration, db_manager, timestamp_file_path, poll_interval_sec=300, event_fetch_limit=100):
        self.openmrs = openmrs_integration
        self.db = db_manager
        self.timestamp_file_path = timestamp_file_path
        self.poll_interval_sec = poll_interval_sec
        self.event_fetch_limit = event_fetch_limit
        self.last_poll_timestamp = self._load_last_timestamp()

        if not self.openmrs.login():
            logging.critical("OpenMRS login failed during poller initialization. Poller may not function correctly.")

    def _load_last_timestamp(self):
        if os.path.exists(self.timestamp_file_path):
            try:
                with open(self.timestamp_file_path, 'r') as f:
                    timestamp_str = f.read().strip()
                    if timestamp_str:
                        dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                        logging.info(f"Loaded last poll timestamp from file: {dt.isoformat()}")
                        return dt
            except (IOError, ValueError, KeyError) as e:
                logging.warning(f"Could not load/parse last poll timestamp from {self.timestamp_file_path}: {e}. Initializing to very old date.")
        
        initial_timestamp = datetime.min.replace(tzinfo=timezone.utc)
        logging.info(f"Initialized last poll timestamp to {initial_timestamp.isoformat()} (very old date).")
        return initial_timestamp

    def _save_last_timestamp(self, timestamp):
        try:
            with open(self.timestamp_file_path, 'w') as f:
                f.write(timestamp.strftime('%Y-%m-%d %H:%M:%S'))
            logging.info(f"Saved new last poll timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        except IOError as e:
            logging.error(f"Failed to save last poll timestamp to {self.timestamp_file_path}: {e}")

    def _extract_patient_uuid_from_object_url(self, object_json_str):
        """Extracts patient UUID from the 'rest' URL in the event record's object JSON."""
        try:
            obj = json.loads(object_json_str)
            rest_url = obj.get('rest')
            if rest_url:
                match = re.search(r'/(patient|person)/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', rest_url)
                if match:
                    return match.group(2)
        except json.JSONDecodeError:
            logging.warning(f"Failed to decode object JSON string: {object_json_str}")
        return None

    def poll_for_new_patients(self):
        logging.info("Starting OpenMRS event record polling cycle...")
        
        latest_timestamp_in_cycle = self.last_poll_timestamp 
        
        startIndex = 0
        total_processed_events = 0
        unique_patient_uuids_to_sync = set()

        patient_event_categories = {
            'patient', 
            'person_attribute', 
            'patient_identifier', 
            'person_name', 
            'person_address'
        }

        current_time_utc = datetime.now(timezone.utc)
        api_from_timestamp = self.last_poll_timestamp 
        api_to_timestamp = current_time_utc 

        while True:
            event_records_response = None
            try:
                event_records_response = self.openmrs.get_event_records(
                    limit=self.event_fetch_limit,
                    startIndex=startIndex,
                    from_timestamp=api_from_timestamp, 
                    to_timestamp=api_to_timestamp       
                )
            except Exception as e:
                logging.error(f"Error fetching event records list from OpenMRS: {e}. Skipping this polling cycle.")
                break

            if not event_records_response or 'results' not in event_records_response:
                logging.warning(f"No event record data received or unexpected response format at startIndex {startIndex}.")
                break

            event_records_list = event_records_response['results']
            if not event_records_list:
                logging.info(f"No more event records found from startIndex {startIndex}. End of pagination.")
                break

            logging.info(f"Processing {len(event_records_list)} event records from startIndex {startIndex}.")

            for event_data in event_records_list:
                total_processed_events += 1
                event_uuid = None
                
                if event_data.get('links') and len(event_data['links']) > 0 and event_data['links'][0].get('uri'):
                    uri = event_data['links'][0]['uri']
                    match = re.search(r'/eventrecord/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', uri)
                    if match:
                        event_uuid = match.group(1)

                if not event_uuid:
                    logging.warning(f"Event record from list is missing UUID in its 'links' URI. Skipping this event. Data: {event_data}")
                    continue 

                logging.info(f"Attempting to fetch full details for event record UUID: {event_uuid}")
                full_event_record = self.openmrs.get_event_record_by_uuid(event_uuid)
                
                # --- ADDED TEMPORARY DEBUGGING LINE HERE ---
                if full_event_record:
                    logging.info(f"Full event record for {event_uuid}:\n{json.dumps(full_event_record, indent=2)}")
                # --- END TEMPORARY DEBUGGING LINE ---

                if not full_event_record:
                    logging.error(f"Failed to fetch full event record details for {event_uuid}. Skipping.")
                    continue
                
                event_timestamp_str = full_event_record.get('timestamp') # This is the line we are debugging
                event_category = full_event_record.get('category') # You might need to get category from full record too
                object_json_str = full_event_record.get('object')

                if not event_timestamp_str:
                    logging.warning(f"Full event record {event_uuid} missing timestamp. Skipping.")
                    continue

                try:
                    event_timestamp_dt = datetime.strptime(event_timestamp_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                except ValueError as ve:
                    logging.error(f"Could not parse timestamp '{event_timestamp_str}' for event {event_uuid} from full record: {ve}. Skipping.")
                    continue

                if event_timestamp_dt > self.last_poll_timestamp:
                    logging.debug(f"New event record found (UUID: {event_uuid}, Category: {event_category}, Timestamp: {event_timestamp_dt.isoformat()}).")

                    if event_category in patient_event_categories:
                        if object_json_str:
                            patient_uuid = self._extract_patient_uuid_from_object_url(object_json_str)

                            if patient_uuid:
                                if patient_uuid not in unique_patient_uuids_to_sync:
                                    logging.info(f"Identified new/updated patient UUID: {patient_uuid}. Adding to list for full patient fetch.")
                                    unique_patient_uuids_to_sync.add(patient_uuid)
                                    
                                if event_timestamp_dt > latest_timestamp_in_cycle:
                                    latest_timestamp_in_cycle = event_timestamp_dt
                            else:
                                logging.warning(f"Could not extract patient UUID from object for event {event_uuid} (Category: {event_category}). Object was: {object_json_str}. Skipping.")
                        else:
                            logging.warning(f"Full event record {event_uuid} (Category: {event_category}) is missing 'object' field. Cannot extract patient UUID. Skipping.")
                    else:
                        logging.debug(f"Event record {event_uuid} (Category: {event_category}) is not a patient-related event. Skipping.")
                else:
                    logging.debug(f"Event record {event_uuid} (Timestamp: {event_timestamp_dt.isoformat()}) is older than or equal to last poll timestamp ({self.last_poll_timestamp.isoformat()}). Skipping.")
            
            if len(event_records_list) < self.event_fetch_limit:
                logging.info(f"Fetched {len(event_records_list)} events, which is less than limit {self.event_fetch_limit}. Assuming last page.")
                break
            else:
                startIndex += self.event_fetch_limit
                logging.info(f"Continuing to next page, startIndex will be {startIndex}.")

        total_new_or_updated_patients = 0
        for p_uuid in unique_patient_uuids_to_sync:
            full_patient_data = self.openmrs.get_patient_by_uuid(p_uuid)
            if full_patient_data:
                self.db.add_event_to_queue(p_uuid, full_patient_data) 
                total_new_or_updated_patients += 1
            else:
                logging.error(f"Failed to fetch full patient data for UUID {p_uuid}. Cannot add to queue.")

        if total_new_or_updated_patients > 0:
            self.last_poll_timestamp = latest_timestamp_in_cycle
            self._save_last_timestamp(self.last_poll_timestamp)
            logging.info(f"Finished polling cycle. Found {total_new_or_updated_patients} new/updated patients. Last poll timestamp updated to: {self.last_poll_timestamp.isoformat()}")
        else:
            logging.info("Finished polling cycle. No new or updated patient-related events found.")

    def run(self):
        logging.info(f"OpenMRS Patient Poller starting, polling every {self.poll_interval_sec} seconds...")
        while True:
            self.poll_for_new_patients()
            time.sleep(self.poll_interval_sec)

# --- QueueProcessor (remains unchanged) ---
class QueueProcessor:
    def __init__(self, patient_middleware, db_manager, process_interval_sec=15, max_retries=3, retry_cool_off_minutes=10):
        self.middleware = patient_middleware
        self.db = db_manager
        self.process_interval_sec = process_interval_sec
        self.max_retries = max_retries
        self.retry_cool_off_minutes = retry_cool_off_minutes

    def process_queue_events(self):
        logging.info("Processing events from the synchronization queue...")
        events = self.db.get_events_from_queue(
            status_list=['PENDING', 'RETRYING'],
            limit=10,
            cool_off_minutes=self.retry_cool_off_minutes
        )
        
        if not events:
            logging.info("No pending or retrying events in the queue.")
            return

        logging.info(f"Found {len(events)} events to process from queue.")

        for event in events:
            event_id, openmrs_patient_uuid, openmrs_full_payload_json, retry_attempts, status = event
            openmrs_full_payload = json.loads(openmrs_full_payload_json)

            logging.info(f"Attempting to synchronize patient (Queue ID: {event_id}, OpenMRS UUID: {openmrs_patient_uuid}). Current status: {status}, Retries: {retry_attempts}")

            try:
                if self.middleware.synchronize_patient(openmrs_full_payload):
                    self.db.update_event_status(event_id, 'SUCCESS')
                    logging.info(f"Patient (OpenMRS UUID: {openmrs_patient_uuid}) synchronized successfully to OpenELIS.")
                else:
                    raise Exception("PatientMiddleware reported synchronization failure.")
            except Exception as e:
                new_retry_attempts = retry_attempts + 1
                error_msg = f"Synchronization failed: {e}"
                
                if new_retry_attempts >= self.max_retries:
                    self.db.update_event_status(event_id, 'AWAITING_MANUAL_REVIEW', error_message=error_msg, increment_retry=True)
                    logging.error(f"Patient (OpenMRS UUID: {openmrs_patient_uuid}) failed after {new_retry_attempts} attempts. Marked for manual review. Error: {error_msg}")
                else:
                    self.db.update_event_status(event_id, 'RETRYING', error_message=error_msg, increment_retry=True)
                    logging.warning(f"Patient (OpenMRS UUID: {openmrs_patient_uuid}) failed. Will retry (attempt {new_retry_attempts}). Error: {error_msg}")

    def run_processor(self):
        logging.info(f"Queue Processor starting, processing every {self.process_interval_sec} seconds...")
        while True:
            self.process_queue_events()
            time.sleep(self.process_interval_sec)