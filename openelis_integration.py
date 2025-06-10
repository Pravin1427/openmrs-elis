# openelis_integration.py

import requests
import json
import logging

# Configure logging for this module
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

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
                logging.info(f"OpenELIS JSESSIONID obtained from login POST: {self.jsessionid}")
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
                    logging.info(f"OpenELIS CSRF token obtained: {self.csrf_token}")
                    logging.info("OpenELIS session successfully established.")
                    return True
                else:
                    logging.error("Failed to retrieve OpenELIS CSRF token from session response.")
                    return False
            else:
                logging.error("OpenELIS session GET indicates not authenticated after login POST.")
                return False

        except requests.exceptions.RequestException as e:
            logging.error(f"OpenELIS login failed: {e}")
            logging.error(f"Response content: {e.response.text if e.response else 'No response'}")
            return False
        except json.JSONDecodeError:
            logging.error("Failed to decode JSON response during OpenELIS login.")
            return False

    def create_openelis_patient(self, patient_data):
        logging.info("Creating patient in OpenELIS...")
        if not self.jsessionid or not self.csrf_token:
            logging.error("OpenELIS session or CSRF token not established. Please login first.")
            return None

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
                timeout=30
            )
            response.raise_for_status()
            logging.info("Patient creation request sent to OpenELIS. Status Code: 200 OK.")
            return True
        except requests.exceptions.HTTPError as e:
            logging.error(f"Failed to create patient in OpenELIS. HTTP Error: {e.response.status_code} - {e.response.text}")
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to create patient in OpenELIS: {e}")
            return False