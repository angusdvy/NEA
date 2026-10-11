# Stage 1

# imports required libraries

import sqlite3
import hashlib
import json
from datetime import date, datetime

DB_PATH = "inventory.db"
simulated_date = None

def get_connection():
    # connects to the database
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def initialise_database():
    # creates the initial tables if they don't already exist
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ("staff", "manager"))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            category TEXT NOT NULL,
            reorder_level INTEGER NOT NULL,
            is_perishable BOOLEAN NOT NULL,
            active BOOLEAN NOT NULL DEFAULT 1
        )
    """)
    

    cur.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            quantity_remaining INTEGER NOT NULL,
            use_by_date DATE NOT NULL,
            received_date DATE NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN
                ("DELIVERY", "SALE", "RETURN", "WASTAGE", "ADJUSTMENT")),
            quantity INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            date DATE NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            table_name TEXT,
            record_id INTEGER,
            old_value TEXT,
            new_value TEXT,
            timestamp DATETIME NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ("staff", hash_password("default"), "staff")
        )
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ("manager", hash_password("default"), "manager")
        )

    conn.commit()
    conn.close()

def hash_password(plaintext):
    # hashes the passwords
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()

def today():
    # checks if simulation mode is active and returns either the simulated or actual date
    if simulated_date is not None:
        return simulated_date
    return date.today()

def edit_system_date(new_date_str, user_id):
    # checks the user trying to edit date is manager then parses the string into date format and updates simulated_date
    conn = get_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()

    if user is None or user["role"] != "manager":
        return {"success": False, "error": "Access Denied"}

    try:
        parsed = datetime.strptime(new_date_str, "%Y-%m-%d").date()
    except ValueError:
        return {"success": False, "error": "Invalid Date"}

    global simulated_date
    simulated_date = parsed
    return {"success": True}

def current_timestamp():
    # combines today()'s date with current time
    now_time = datetime.now().time()
    return datetime.combine(today(), now_time)

def record_user_action(user_id, action_type):
    # writes an audit entry with no record target
    conn = get_connection()
    conn.execute(
        """INSERT INTO audit_log
            (user_id, action_type, table_name, record_id, old_value, new_value, timestamp)
            VALUES (?, ?, NULL, NULL, NULL, NULL, ?)""",
        (user_id, action_type, current_timestamp())
    )
    conn.commit()
    conn.close()

def record_product_change(user_id, product_id, action_type, old_value, new_value):
    conn = get_connection()
    conn.execute(
        """INSERT INTO audit_log
            (user_id, action_type, table_name, record_id, old_value, new_value, timestamp)
            VALUES (?, ?, "products", ?, ?, ?, ?)""",
        (
            user_id, action_type, product_id,
            json.dumps(old_value) if old_value is not None else None,
            json.dumps(new_value) if new_value is not None else None,
            current_timestamp()
        )
    )
    conn.commit()
    conn.close()

def record_stock_movement(user_id, movement_id, movement_type, quantity):
    # writes a stock movement audit entry 
    conn = get_connection()
    conn.execute(
        """INSERT INTO audit_log
            (user_id, action_type, table_name, record_id, old_value, new_value, timestamp)
            VALUES (?, ?, "stock_movements", ?, NULL, ?, ?)""",
        (user_id, movement_type, movement_id, str(quantity), current_timestamp())
    )
    conn.commit()
    conn.close()