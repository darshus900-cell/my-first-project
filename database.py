import os
import re
import sqlite3
import json
import csv
import numpy as np
from datetime import datetime

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "attendance.db")
FACES_DIR = os.path.join(DB_DIR, "faces")


def _sanitize_filename(name):
    """Convert a display name into a safe filename stem."""
    safe = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_")
    return safe or "user"


def _parse_created_at(created_at):
    """Parse SQLite created_at into (date YYYY-MM-DD, time HH:MM:SS)."""
    if not created_at:
        now = datetime.now()
        return now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")
    try:
        text = str(created_at).replace("T", " ").strip()
        if "." in text:
            text = text.split(".")[0]
        dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(str(created_at)[:10], "%Y-%m-%d")
        except ValueError:
            dt = datetime.now()
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")


def init_db():
    """Initialize the database and create tables if they do not exist."""
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)
    if not os.path.exists(FACES_DIR):
        os.makedirs(FACES_DIR)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            face_encoding TEXT NOT NULL,
            face_image_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            check_in_method TEXT DEFAULT 'Face Recognition',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, date)
        )
    """)

    # Migrate older databases
    cursor.execute("PRAGMA table_info(users)")
    user_columns = [row[1] for row in cursor.fetchall()]
    if "face_image_path" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN face_image_path TEXT")

    cursor.execute("PRAGMA table_info(attendance)")
    att_columns = [row[1] for row in cursor.fetchall()]
    if "check_in_method" not in att_columns:
        cursor.execute(
            "ALTER TABLE attendance ADD COLUMN check_in_method TEXT DEFAULT 'Face Recognition'"
        )

    conn.commit()
    conn.close()


def sync_registered_users_to_attendance():
    """Backfill historical attendance rows from registration dates only (not today)."""
    if not os.path.exists(DB_PATH):
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT name, created_at FROM users")
        for name, created_at in cursor.fetchall():
            reg_date, reg_time = _parse_created_at(created_at)
            cursor.execute(
                "SELECT id FROM attendance WHERE name = ? AND date = ?",
                (name, reg_date),
            )
            if not cursor.fetchone():
                cursor.execute(
                    """INSERT OR IGNORE INTO attendance
                       (name, date, time, check_in_method) VALUES (?, ?, ?, ?)""",
                    (name, reg_date, reg_time, "Registration"),
                )
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error syncing attendance: {e}")
    finally:
        conn.close()


def save_face_image(name, image_bgr):
    """
    Save a cropped face image (BGR numpy array from OpenCV) to disk.
    Returns the relative path stored in the database.
    """
    import cv2

    init_db()
    filename = f"{_sanitize_filename(name)}.jpg"
    filepath = os.path.join(FACES_DIR, filename)
    cv2.imwrite(filepath, image_bgr)
    return os.path.join("faces", filename)


def get_face_image_path(name):
    """Return absolute path to a user's stored face image, or None."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT face_image_path FROM users WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row and row["face_image_path"]:
            full_path = os.path.join(DB_DIR, row["face_image_path"])
            if os.path.exists(full_path):
                return full_path
    finally:
        conn.close()
    return None


def register_user(name, face_encoding, face_image_bgr=None):
    """
    Register a new user with their face encoding and optional face snapshot.
    face_encoding: numpy array of shape (128,) or list
    face_image_bgr: optional OpenCV BGR image of the cropped face region
    """
    name = (name or "").strip()
    if not name:
        return False, "Please enter a valid employee name."

    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if isinstance(face_encoding, np.ndarray):
        encoding_str = json.dumps(face_encoding.tolist())
    else:
        encoding_str = json.dumps(face_encoding)

    image_path = None
    if face_image_bgr is not None:
        image_path = save_face_image(name, face_image_bgr)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        cursor.execute("SELECT name FROM users WHERE LOWER(name) = LOWER(?)", (name,))
        row = cursor.fetchone()
        stored_name = row[0] if row else name

        if row:
            if image_path:
                cursor.execute(
                    """UPDATE users SET face_encoding = ?, face_image_path = ?
                       WHERE LOWER(name) = LOWER(?)""",
                    (encoding_str, image_path, name),
                )
            else:
                cursor.execute(
                    "UPDATE users SET face_encoding = ? WHERE LOWER(name) = LOWER(?)",
                    (encoding_str, name),
                )
            message = f"Student '{stored_name}' updated successfully."
        else:
            cursor.execute(
                """INSERT INTO users (name, face_encoding, face_image_path, created_at)
                   VALUES (?, ?, ?, ?)""",
                (name, encoding_str, image_path, now_str),
            )
            stored_name = name
            message = f"Student '{stored_name}' registered successfully."

        conn.commit()
        success = True

        marked, att_msg = mark_attendance(stored_name, method="Registration")
        if marked:
            message += " Listed in Attendance Records."
        elif "updated" in att_msg.lower():
            message += " Attendance record updated."

    except sqlite3.IntegrityError:
        success = False
        message = f"Employee '{name}' could not be saved (duplicate or invalid data)."
    except sqlite3.Error as e:
        success = False
        message = f"Database error: {str(e)}"
    finally:
        conn.close()

    return success, message


def delete_user(name):
    """Delete a user, their registration, and stored face image."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT face_image_path FROM users WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row and row[0]:
            img_path = os.path.join(DB_DIR, row[0])
            if os.path.exists(img_path):
                os.remove(img_path)

        cursor.execute("DELETE FROM attendance WHERE name = ?", (name,))
        cursor.execute("DELETE FROM users WHERE name = ?", (name,))
        conn.commit()
        return True, f"User '{name}' deleted successfully."
    except sqlite3.Error as e:
        return False, f"Database error: {str(e)}"
    finally:
        conn.close()


def get_all_users():
    """Retrieve all registered users and their face encodings."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    users = []
    try:
        cursor.execute(
            "SELECT name, face_encoding, face_image_path, created_at FROM users ORDER BY created_at DESC"
        )
        rows = cursor.fetchall()
        for row in rows:
            encoding_list = json.loads(row["face_encoding"])
            encoding = np.array(encoding_list, dtype=np.float64)
            users.append({
                "name": row["name"],
                "encoding": encoding,
                "face_image_path": row["face_image_path"],
                "created_at": row["created_at"],
            })
    except sqlite3.Error as e:
        print(f"Error fetching users: {e}")
    finally:
        conn.close()

    return users


def get_registered_users_public():
    """Return user metadata for display (no encodings)."""
    users = get_all_users()
    today = datetime.now().strftime("%Y-%m-%d")
    logs_today = get_attendance_logs(date_filter=today)
    present_names = {log["name"] for log in logs_today}

    result = []
    for user in users:
        result.append({
            "name": user["name"],
            "created_at": user["created_at"],
            "face_image_path": user["face_image_path"],
            "present_today": user["name"] in present_names,
        })
    return result


def mark_attendance(name, method="Face Recognition"):
    """
    Mark or update attendance for today. Face recognition updates the time
    each time the user is recognized again on the same day.
    Returns (success, message).
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M:%S")

    try:
        cursor.execute(
            "SELECT id, check_in_method FROM attendance WHERE name = ? AND date = ?",
            (name, current_date),
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                """UPDATE attendance
                   SET time = ?, check_in_method = ?, timestamp = CURRENT_TIMESTAMP
                   WHERE name = ? AND date = ?""",
                (current_time, method, name, current_date),
            )
            conn.commit()
            return True, f"Attendance updated for {name} at {current_time}."
        else:
            cursor.execute(
                """INSERT INTO attendance (name, date, time, check_in_method)
                   VALUES (?, ?, ?, ?)""",
                (name, current_date, current_time, method),
            )
            conn.commit()
            return True, f"Attendance marked for {name} at {current_time}."
    except sqlite3.Error as e:
        return False, f"Database error: {str(e)}"
    finally:
        conn.close()


def get_attendance_logs(date_filter=None):
    """Get all attendance logs, optionally filtered by date (YYYY-MM-DD)."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    logs = []
    try:
        if date_filter:
            cursor.execute(
                "SELECT name, date, time FROM attendance WHERE date = ? ORDER BY timestamp DESC",
                (date_filter,),
            )
        else:
            cursor.execute(
                "SELECT name, date, time FROM attendance ORDER BY timestamp DESC"
            )

        for row in cursor.fetchall():
            logs.append({
                "name": row["name"],
                "date": row["date"],
                "time": row["time"],
            })
    except sqlite3.Error as e:
        print(f"Error fetching attendance logs: {e}")
    finally:
        conn.close()

    return logs


def get_attendance_records(date_filter=None):
    """
    Return attendance records for the UI — one entry per registered user with details.
    Shows today's face-recognition check-in when available.
    """
    init_db()
    sync_registered_users_to_attendance()
    users = get_all_users()
    if not users:
        return []

    today = datetime.now().strftime("%Y-%m-%d")
    target_date = date_filter or today

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    records = []

    try:
        for user in users:
            name = user["name"]
            registered_at = user["created_at"]

            cursor.execute(
                """SELECT date, time, check_in_method FROM attendance
                   WHERE name = ? AND date = ?
                   ORDER BY timestamp DESC LIMIT 1""",
                (name, target_date),
            )
            row = cursor.fetchone()

            if row:
                method = row["check_in_method"] or "Face Recognition"
                status = "Present" if method == "Face Recognition" else "Registered"
                records.append({
                    "name": name,
                    "date": row["date"],
                    "time": row["time"],
                    "status": status,
                    "check_in_method": method,
                    "registered_at": registered_at,
                })
            else:
                reg_date, reg_time = _parse_created_at(registered_at)
                records.append({
                    "name": name,
                    "date": target_date if date_filter else today,
                    "time": "—",
                    "status": "Absent" if (not date_filter or reg_date <= target_date) else "Not Present",
                    "check_in_method": "Not Checked In",
                    "registered_at": registered_at,
                })

        records.sort(key=lambda r: (r["date"], r["time"]), reverse=True)
    except sqlite3.Error as e:
        print(f"Error building attendance records: {e}")
    finally:
        conn.close()

    return records


def get_today_statistics():
    """Return dashboard statistics for the current day."""
    init_db()
    sync_registered_users_to_attendance()
    today = datetime.now().strftime("%Y-%m-%d")
    users = get_all_users()
    logs_today = get_attendance_logs(date_filter=today)
    registered_names = {u["name"] for u in users}
    present_names = {log["name"] for log in logs_today if log["name"] in registered_names}

    return {
        "total_registered": len(users),
        "attendance_marked_today": len(logs_today),
        "present_today": len(present_names),
        "absent_today": max(0, len(users) - len(present_names)),
        "recent_checkins": logs_today[:10],
        "date": today,
    }


def export_to_csv(csv_filename="attendance_records.csv"):
    """Export all attendance logs to a CSV file in the data directory."""
    init_db()
    csv_path = os.path.join(DB_DIR, csv_filename)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT name, date, time, check_in_method FROM attendance ORDER BY timestamp DESC"
        )
        rows = cursor.fetchall()

        with open(csv_path, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["Name", "Date", "Login Time", "Check-In Method"])
            writer.writerows(rows)

        return True, f"Successfully exported logs to {csv_path}"
    except Exception as e:
        return False, f"Export failed: {str(e)}"
    finally:
        conn.close()


def export_users_to_csv(csv_filename="registered_users.csv"):
    """Export registered user list to CSV."""
    init_db()
    csv_path = os.path.join(DB_DIR, csv_filename)
    users = get_registered_users_public()

    try:
        with open(csv_path, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["Name", "Registered On", "Present Today"])
            for user in users:
                writer.writerow([
                    user["name"],
                    user["created_at"],
                    "Yes" if user["present_today"] else "No",
                ])
        return True, f"Successfully exported users to {csv_path}"
    except Exception as e:
        return False, f"Export failed: {str(e)}"
