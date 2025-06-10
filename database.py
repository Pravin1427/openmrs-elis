import psycopg2
from psycopg2 import sql
import logging
import json # New import for json.dumps in add_event_to_queue

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s') # Changed to INFO for better visibility of DB operations

class DatabaseManager:
    def __init__(self, db_config):
        self.db_config = db_config
        self.conn = None

    def connect(self):
        """Establishes a connection to the PostgreSQL database."""
        if self.conn is None or self.conn.closed:
            logging.info("Attempting to connect to PostgreSQL database...")
            try:
                self.conn = psycopg2.connect(**self.db_config)
                self.conn.autocommit = True # We might want autocommit for simple inserts/updates
                logging.info("Successfully connected to PostgreSQL database.")
                return True
            except psycopg2.Error as e:
                logging.error(f"Error connecting to PostgreSQL database: {e}")
                self.conn = None
                return False
        return True # Already connected

    def disconnect(self):
        """Closes the database connection."""
        if self.conn:
            logging.info("Disconnecting from PostgreSQL database.")
            self.conn.close()
            self.conn = None

    def _execute_query(self, query, params=None, fetch_one=False, fetch_all=False):
        """Internal helper to execute SQL queries."""
        if not self.connect():
            logging.error("No database connection available.")
            return None

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params)
                if fetch_one:
                    return cur.fetchone()
                if fetch_all:
                    return cur.fetchall()
                return True # For DDL/DML that doesn't return data
        except psycopg2.Error as e:
            logging.error(f"Database query failed: {query} with params {params}. Error: {e}")
            # Optionally, attempt to reconnect or mark connection as bad if error suggests it
            return None
        except Exception as e:
            logging.error(f"An unexpected error occurred during database query: {e}")
            return None

    def create_tables(self):
        """Creates the necessary tables if they don't exist."""
        logging.info("Checking/creating database tables...")
        
        # The 'sync_status' table was primarily for atom feed. With file-based timestamp, it's not strictly needed
        # but if you foresee other global sync status, you can keep it.
        # For now, I'll keep it as the previous code had it, but note its primary function for atom_feed_id is gone.
        sync_status_table_query = sql.SQL("""
            CREATE TABLE IF NOT EXISTS {} (
                id SERIAL PRIMARY KEY,
                last_processed_atom_feed_id TEXT UNIQUE, -- Made UNIQUE not NOT NULL as it might not be used or can be null
                timestamp_last_updated TIMESTAMP DEFAULT NOW()
            );
        """).format(sql.Identifier('sync_status'))

        event_queue_table_query = sql.SQL("""
            CREATE TABLE IF NOT EXISTS {} (
                id SERIAL PRIMARY KEY,
                openmrs_patient_uuid TEXT UNIQUE NOT NULL,
                openmrs_full_payload JSONB NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                retry_attempts INTEGER NOT NULL DEFAULT 0,
                created_time TIMESTAMP NOT NULL DEFAULT NOW(),
                last_attempt_time TIMESTAMP,
                error_message TEXT
            );
        """).format(sql.Identifier('event_queue'))

        try:
            self._execute_query(sync_status_table_query)
            logging.info("Table 'sync_status' checked/created.")
            self._execute_query(event_queue_table_query)
            logging.info("Table 'event_queue' checked/created.")
            return True
        except Exception as e:
            logging.error(f"Failed to create tables: {e}")
            return False

    # These methods are now less critical or might not be used by the new poller,
    # but kept for completeness if other parts of your system use them.
    # The new poller uses a file for its timestamp.
    def get_last_processed_atom_feed_id(self):
        """Retrieves the last processed Atom Feed ID (less relevant now)."""
        query = sql.SQL("SELECT last_processed_atom_feed_id FROM {} ORDER BY timestamp_last_updated DESC LIMIT 1").format(sql.Identifier('sync_status'))
        result = self._execute_query(query, fetch_one=True)
        return result[0] if result else None

    def set_last_processed_atom_feed_id(self, atom_feed_id):
        """Sets or updates the last processed Atom Feed ID (less relevant now)."""
        query = sql.SQL("""
            INSERT INTO {} (last_processed_atom_feed_id) VALUES (%s)
            ON CONFLICT (last_processed_atom_feed_id) DO UPDATE
            SET timestamp_last_updated = NOW();
        """).format(sql.Identifier('sync_status'))
        return self._execute_query(query, (atom_feed_id,))

    def add_event_to_queue(self, patient_uuid, full_payload):
        """Adds a new patient synchronization event to the queue."""
        # Using DO NOTHING on conflict for uniqueness; assuming we only queue a patient once by UUID
        query = sql.SQL("""
            INSERT INTO {} (openmrs_patient_uuid, openmrs_full_payload)
            VALUES (%s, %s)
            ON CONFLICT (openmrs_patient_uuid) DO NOTHING;
        """).format(sql.Identifier('event_queue'))
        return self._execute_query(query, (patient_uuid, json.dumps(full_payload)))

    def get_events_from_queue(self, status_list=['PENDING', 'RETRYING'], limit=10, cool_off_minutes=10):
        """
        Fetches events from the queue for processing.
        Includes logic for cool-off period for 'RETRYING' events.
        """
        query = sql.SQL("""
            SELECT id, openmrs_patient_uuid, openmrs_full_payload, retry_attempts, status
            FROM {}
            WHERE status IN %s
              AND (
                status = 'PENDING'
                OR (status = 'RETRYING' AND (last_attempt_time IS NULL OR last_attempt_time <= NOW() - INTERVAL %s ))
              )
            ORDER BY created_time ASC, last_attempt_time ASC
            LIMIT %s;
        """).format(sql.Identifier('event_queue'))
        
        # Interval requires a string format for SQL, e.g., '10 minutes'
        interval_str = f"{cool_off_minutes} minutes"
        
        return self._execute_query(query, (tuple(status_list), interval_str, limit), fetch_all=True)

    def update_event_status(self, event_id, status, error_message=None, increment_retry=False):
        """Updates the status of an event in the queue."""
        updates = ["status = %s", "last_attempt_time = NOW()"]
        params_values = [status]
        
        if increment_retry:
            updates.append("retry_attempts = retry_attempts + 1")
        if error_message is not None: # Use is not None to allow empty string
            updates.append("error_message = %s")
            params_values.append(error_message)

        params_values.append(event_id) # Add event_id last for WHERE clause

        query = sql.SQL("UPDATE {} SET {} WHERE id = %s").format(
            sql.Identifier('event_queue'),
            sql.SQL(', ').join(sql.SQL(u) for u in updates)
        )
        
        return self._execute_query(query, tuple(params_values))