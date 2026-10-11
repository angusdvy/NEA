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

# Stage 2

def authenticate_user(username, password):
    # looks up user by username, hashes password and compares against stored hash, if successful logs a LOGIN action
    conn = get_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()

    if user is None:
        return False

    if hash_password(password) == user["password_hash"]:
        record_user_action(user["id"], "LOGIN")
        return user
    else:
        return False

# Stage 3

def add_product(name, price, category, reorder_level, is_perishable, user_id):
    # adds a product to database and logs the change
    if name == "" or price < 0 or reorder_level < 0:
        return {"success": False, "error": "Invalid Input"}

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO products (name, price, category, reorder_level, is_perishable, active)
        VALUES (?, ?, ?, ?, ?, 1)""",
        (name, price, category, reorder_level, is_perishable)
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()

    record_product_change(
        user_id, new_id, "CREATE", None,
        {"name": name, "price": price, "category": category, "reorder_level": reorder_level}
    )
    return {"success": True, "id": new_id}

def edit_product(product_id, name, price, category, reorder_level, user_id):
    # edits a product in the database and logs the change
    conn = get_connection()
    old_values = conn.execute(
        "SELECT * FROM products WHERE id = ?", (product_id,)
    ).fetchone()

    if old_values is None:
        conn.close()
        return {"success": False, "error": "Not found"}

    if name == "" or price < 0 or reorder_level < 0:
        conn.close()
        return {"success": False, "error": "Inalid Input"}

    conn.execute(
        """UPDATE products SET name = ?, price = ?, category = ?, reorder_level = ?
        WHERE id = ?""",
        (name, price, category, reorder_level, product_id)
    )
    conn.commit()
    conn.close()

    old_dict = dict(old_values)
    new_dict = {"name": name, "price": price, "category": category, "reorder_level": reorder_level}
    record_product_change(user_id, product_id, "EDIT", old_dict, new_dict)
    return {"success": True}

def delete_product(product_id, user_id):
    # deletes a product from the database after checking for dependencies and logs the change
    conn = get_connection()
    old_values = conn.execute(
        "SELECT * FROM products WHERE id = ?", (product_id,)
    ).fetchone()

    if old_values is None:
        conn.close()
        return {"success": False, "error": "Not found"}

    movement_count = conn.execute(
        "SELECT COUNT(*) FROM stock_movements WHERE product_id = ?", (product_id,)
    ).fetchone()[0]
    batch_count = conn.execute(
        "SELECT COUNT (*) FROM batches WHERE product_id = ?", (product_id,)
    ).fetchone()[0]
    dependencies = movement_count + batch_count

    if dependencies > 0:
        conn.close()
        return {"success": False, "error": "Cannot delete"}

    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()

    record_product_change(user_id, product_id, "DELETE", dict(old_values), None)
    return {"success": True}

def archive_product(product_id, user_id):
    # archives a product from the database and logs the change
    conn = get_connection()
    old_values = conn.execute(
        "SELECT * FROM products WHERE id = ?", (product_id,)
    ).fetchone()

    if old_values is None:
        conn.close()
        return {"success": False, "error": "Not found"}

    conn.execute("UPDATE products SET active = 0 WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()

    old_dict = dict(old_values)
    new_dict = dict(old_values)
    new_dict["active"] = False
    record_product_change(user_id, product_id, "ARCHIVE", old_dict, new_dict)
    return {"success": True}

def search_products(term):
    # allows the database to be searched from a term by the name category or id
    conn = get_connection()
    like_term = f"%{term}%"
    results = conn.execute(
        """SELECT * FROM products
        WHERE (name LIKE ? OR category LIKE ? OR CAST(id AS TEXT) LIKE ?)
        AND active = 1""",
        (like_term, like_term, like_term)
    ).fetchall()
    conn.close()
    return results

def sort_products(field, direction="ASC"):
    # allows the database to be sorted by a field in ASC or DESC
    conn = get_connection()
    query = f"SELECT * FROM products WHERE active = 1 ORDER BY {field} {direction}"
    results = conn.execute(query).fetchall()
    return results

def get_product_list(search_term=None, sort_field=None, sort_direction="ASC"):
    # fetches a list of either all products or a specific search term and allows them to be sorted
    if search_term:
        products = search_products(search_term)
    else:
        conn = get_connection()
        products = conn.execute("SELECT * FROM products WHERE active = 1").fetchall()
        conn.close()

    if sort_field:
        rows = [dict(r) for r in products]
        reverse = (sort_direction.upper() == "DESC")
        rows.sort(key=lambda r: r[sort_field], reverse=reverse)
        return rows

    return products