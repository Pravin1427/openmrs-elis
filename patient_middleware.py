# patient_middleware.py

import json
import logging
from datetime import datetime, timezone

# Configure logging for this module
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class PatientMiddleware:
    def __init__(self, openmrs_integration, openelis_integration):
        self.openmrs = openmrs_integration
        self.openelis = openelis_integration

    def synchronize_patient(self, openmrs_patient_response):
        logging.info("Attempting to synchronize patient from OpenMRS to OpenELIS.")

        # Ensure OpenMRS and OpenELIS are logged in before attempting sync
        # These will re-login if the session has expired.
        if not self.openmrs.login(): 
            logging.error("Failed to log in to OpenMRS. Aborting synchronization.")
            return False
        
        if not self.openelis.login(): 
            logging.error("Failed to log in to OpenELIS or retrieve CSRF token. Aborting synchronization.")
            return False

        openmrs_person = openmrs_patient_response.get('person', {})
        
        preferred_name_obj = openmrs_person.get('preferredName', {})
        first_name = preferred_name_obj.get('givenName', '')
        last_name = preferred_name_obj.get('familyName', '')
        
        if not first_name and not last_name:
            preferred_name_display = preferred_name_obj.get('display', '')
            name_parts = preferred_name_display.split(' ')
            if len(name_parts) >= 2:
                first_name = name_parts[0]
                last_name = name_parts[-1]
            elif len(name_parts) == 1:
                first_name = name_parts[0]

        logging.info(f"Parsed OpenMRS first name: '{first_name}'")
        logging.info(f"Parsed OpenMRS last name: '{last_name}'")

        openmrs_patient_id = ""
        identifiers_list = openmrs_patient_response.get('identifiers', [])
        if identifiers_list:
            # Prefer 'preferred' identifier, otherwise take the first one
            preferred_identifier = next((ident for ident in identifiers_list if ident.get('preferred')), None)
            if preferred_identifier:
                identifier_display = preferred_identifier.get('display', '')
            else:
                identifier_display = identifiers_list[0].get('display', '')

            if ' = ' in identifier_display:
                openmrs_patient_id = identifier_display.split(' = ')[1].strip()
            else:
                openmrs_patient_id = identifier_display.strip()
            
        logging.info(f"Parsed OpenMRS Patient ID: '{openmrs_patient_id}'")

        openmrs_addresses = openmrs_person.get('preferredAddress', {})
        logging.debug(f"Extracted OpenMRS addresses: {json.dumps(openmrs_addresses, indent=2)}")
        
        openmrs_attributes = openmrs_person.get('attributes', [])
        logging.debug(f"Extracted OpenMRS attributes: {json.dumps(openmrs_attributes, indent=2)}")

        phone_number = ""
        for attr in openmrs_attributes:
            # Assuming this UUID is for the "Phone Number" attribute type
            if attr.get('attributeType', {}).get('uuid') == "14d4f066-15f5-102d-96e4-000c29c2a5d7":
                phone_number = attr.get('value', '')
                break
        logging.info(f"Parsed OpenMRS phone number: '{phone_number}'")
        
        birthdate_openmrs = openmrs_person.get('birthdate', '')
        birthdate_elis = ""
        if birthdate_openmrs:
            try:
                # Replace +0000 with +00:00 for datetime.fromisoformat
                if '+' in birthdate_openmrs and '.' in birthdate_openmrs: # Handles format like "YYYY-MM-DDTHH:MM:SS.sss+0000"
                    dt_object = datetime.fromisoformat(birthdate_openmrs.replace('+0000', '+00:00'))
                elif 'T' in birthdate_openmrs and 'Z' in birthdate_openmrs: # Handles "YYYY-MM-DDTHH:MM:SSZ"
                    dt_object = datetime.fromisoformat(birthdate_openmrs.replace('Z', '+00:00'))
                else: # Handles "YYYY-MM-DD"
                    dt_object = datetime.strptime(birthdate_openmrs, "%Y-%m-%d")
                birthdate_elis = dt_object.strftime("%d/%m/%Y")
            except ValueError:
                logging.warning(f"Could not parse OpenMRS birthdate: {birthdate_openmrs}. Using empty string for OpenELIS.")
        logging.info(f"Parsed OpenMRS birthdate for ELIS: '{birthdate_elis}'")

        openelis_patient_payload = {
            "patientUpdateStatus": "ADD",
            "nationalId": openmrs_patient_id,
            "subjectNumber": openmrs_patient_id, # Often same as nationalId in OpenELIS
            "lastName": last_name,
            "firstName": first_name,
            "gender": openmrs_person.get('gender', ''),
            "birthDateForDisplay": birthdate_elis,
            "primaryPhone": phone_number,
            "streetAddress": openmrs_addresses.get('address1', ''),
            "city": openmrs_addresses.get('cityVillage', ''),
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
        logging.info(f"Transformed patient data for OpenELIS: {json.dumps(openelis_patient_payload, indent=2)}")

        if self.openelis.create_openelis_patient(openelis_patient_payload):
            logging.info("Patient successfully synchronized to OpenELIS.")
            return True
        else:
            logging.error("Failed to synchronize patient to OpenELIS.")
            return False