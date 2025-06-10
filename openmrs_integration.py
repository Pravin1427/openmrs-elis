# --- openmrs_integration.py (UPDATED AGAIN) ---

import requests
import json
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class OpenMRSIntegration:
    def __init__(self, base_url, username, password, location_uuid):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.location_uuid = location_uuid
        self.session = requests.Session()
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.jsessionid = None
        self.authenticated = False

    def login(self):
        logging.info("Attempting to log in to OpenMRS...")
        
        try:
            session_check_url = f"{self.base_url}/ws/rest/v1/session"
            session_response = self.session.get(session_check_url, headers=self.headers, auth=(self.username, self.password), verify=False, timeout=10)
            session_response.raise_for_status()
            session_data = session_response.json()
            
            if session_data.get('authenticated'):
                self.authenticated = True
                self.jsessionid = self.session.cookies.get('JSESSIONID')
                logging.info("OpenMRS initial session GET successful and authenticated.")
                
                current_session_location_uuid = None
                session_location_data = session_data.get('sessionLocation')
                if session_location_data: 
                    current_session_location_uuid = session_location_data.get('uuid')

                if not current_session_location_uuid == self.location_uuid:
                    logging.info(f"OpenMRS current session location ('{current_session_location_uuid}') does not match required ('{self.location_uuid}'). Setting new location.")
                    return self._set_session_location()
                logging.info(f"OpenMRS session location is already set to '{self.location_uuid}'.")
                return True
            else:
                logging.info("OpenMRS session not authenticated, proceeding with new login.")
        except requests.exceptions.RequestException as e:
            logging.warning(f"Session check failed: {e}. Attempting full login.")

        try:
            session_check_url = f"{self.base_url}/ws/rest/v1/session"
            session_response = self.session.get(session_check_url, headers=self.headers, auth=(self.username, self.password), verify=False, timeout=10)
            session_response.raise_for_status()
            session_data = session_response.json()

            if session_data.get('authenticated'):
                self.authenticated = True
                self.jsessionid = self.session.cookies.get('JSESSIONID')
                logging.info("OpenMRS successfully authenticated and retrieved session data.")

                current_session_location_uuid = None
                session_location_data = session_data.get('sessionLocation')
                if session_location_data:
                    current_session_location_uuid = session_location_data.get('uuid')

                if not current_session_location_uuid == self.location_uuid:
                    logging.info(f"OpenMRS current session location ('{current_session_location_uuid}') does not match required ('{self.location_uuid}'). Setting new location.")
                    return self._set_session_location()
                logging.info(f"OpenMRS session location is already set to '{self.location_uuid}'.")
                return True
            else:
                logging.error("OpenMRS authentication failed after session check.")
                self.authenticated = False
                return False
        except requests.exceptions.RequestException as e:
            logging.error(f"OpenMRS login failed: {e}")
            self.authenticated = False
            return False

    def _set_session_location(self):
        """Sets the session location for the authenticated user."""
        try:
            location_url = f"{self.base_url}/ws/rest/v1/session"
            payload = {"sessionLocation": self.location_uuid}
            response = self.session.post(location_url, headers=self.headers, auth=(self.username, self.password), json=payload, verify=False, timeout=10)
            response.raise_for_status()
            logging.info(f"OpenMRS session location set successfully to {self.location_uuid}. Login complete.")
            return True
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to set OpenMRS session location: {e}")
            return False

    def get_patient_by_uuid(self, uuid):
        """Fetches a full patient record by UUID."""
        if not self.authenticated:
            logging.error("Not authenticated with OpenMRS. Please login first.")
            if not self.login():
                return None
        
        patient_url = f"{self.base_url}/ws/rest/v1/patient/{uuid}?v=full"
        try:
            response = self.session.get(patient_url, headers=self.headers, auth=(self.username, self.password), verify=False, timeout=10)
            response.raise_for_status()
            logging.debug(f"Fetched patient data for UUID {uuid}.")
            return response.json()
        except requests.exceptions.HTTPError as e:
            logging.error(f"Failed to fetch patient {uuid} from OpenMRS. HTTP Error: {e.response.status_code} - {e.response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch patient {uuid} from OpenMRS: {e}")
            return None

    def get_event_records(self, limit=100, startIndex=0, from_timestamp=None, to_timestamp=None): # Note: from_timestamp/to_timestamp are now ignored for API call
        """
        Fetches event records from the custom OpenMRS eventrecord REST endpoint.
        Server-side date filtering appears to be non-functional, so we fetch all 
        and filter client-side.
        """
        if not self.authenticated:
            logging.error("Not authenticated with OpenMRS. Please login first.")
            if not self.login():
                return None

        event_record_url = f"{self.base_url}/ws/rest/v1/eventrecord"
        params = {
            "limit": limit,
            "startIndex": startIndex,
            "v": "full" # Keep v=full to try and get more details, though still need individual fetches
        }
        
        # *** REMOVED fromTimestamp and toTimestamp from params ***
        # They were causing the API to return empty results.
        # Date filtering will now happen client-side in poller_and_processor.py

        logging.info(f"Fetching event records from OpenMRS API: {event_record_url} with params: {params}")

        try:
            response = self.session.get(event_record_url, headers=self.headers, params=params, auth=(self.username, self.password), verify=False, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logging.error(f"Failed to fetch event records from OpenMRS. HTTP Error: {e.response.status_code} - {e.response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch event records from OpenMRS: {e}")
            return None

    def get_event_record_by_uuid(self, uuid):
        """Fetches a single event record by its UUID to get its full details including the 'object' field."""
        if not self.authenticated:
            logging.error("Not authenticated with OpenMRS. Please login first.")
            if not self.login():
                return None
        
        event_record_detail_url = f"{self.base_url}/ws/rest/v1/eventrecord/{uuid}?v=full"
        logging.info(f"Fetching full event record details for UUID: {uuid}")
        try:
            response = self.session.get(event_record_detail_url, headers=self.headers, auth=(self.username, self.password), verify=False, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logging.error(f"Failed to fetch full event record {uuid} from OpenMRS. HTTP Error: {e.response.status_code} - {e.response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch full event record {uuid} from OpenMRS: {e}")
            return None