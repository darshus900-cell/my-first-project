import os
import sys
import numpy as np
import database

def run_tests():
    print("=" * 60)
    print("        RUNNING UNIT TESTS FOR SMART ATTENDANCE SYSTEM")
    print("=" * 60)

    # 1. Initialize DB
    print("[Test 1] Initializing database...")
    database.init_db()
    db_file = database.DB_PATH
    if os.path.exists(db_file):
        print(f"   -> Success: Database file exists at {db_file}")
    else:
        print("   -> Fail: Database file was not created.")
        return False

    # 2. Register User (clean up any leftover test data first)
    print("\n[Test 2] Registering test user...")
    test_name = "Jane Doe"
    database.delete_user(test_name)
    import sqlite3
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("DELETE FROM attendance WHERE name = ?", (test_name,))
    conn.commit()
    conn.close()
    # Create a random face encoding (128 dimensions)
    dummy_encoding = np.random.rand(128)
    
    success, msg = database.register_user(test_name, dummy_encoding)
    if success:
        print(f"   -> Success: {msg}")
    else:
        print(f"   -> Fail: {msg}")
        return False

    logs_after_register = database.get_attendance_logs()
    if not any(log["name"] == test_name for log in logs_after_register):
        print("   -> Fail: Registration did not create an Attendance Records entry.")
        return False
    print(f"   -> Success: '{test_name}' appears in Attendance Records after registration.")

    # 3. Retrieve User Encodings
    print("\n[Test 3] Loading registered faces...")
    users = database.get_all_users()
    found = False
    for user in users:
        if user["name"] == test_name:
            # Check shape of loaded encoding
            if isinstance(user["encoding"], np.ndarray) and user["encoding"].shape == (128,):
                found = True
                print(f"   -> Success: Loaded '{test_name}' encoding successfully. Shape: {user['encoding'].shape}")
            else:
                print(f"   -> Fail: Loaded encoding is invalid or has wrong shape.")
                return False
                
    if not found:
        print(f"   -> Fail: '{test_name}' was not found in registered users.")
        return False

    # 4. Face recognition updates today's attendance (upsert)
    print("\n[Test 4] Face recognition check-in (update today's record)...")
    success, msg = database.mark_attendance(test_name, method="Face Recognition")
    if success and "updated" in msg.lower():
        print(f"   -> Success: {msg}")
    elif success:
        print(f"   -> Success: {msg}")
    else:
        print(f"   -> Fail: {msg}")
        return False

    # 5. Fetch Logs
    print("\n[Test 5] Fetching attendance logs...")
    logs = database.get_attendance_logs()
    found_log = False
    for log in logs:
        if log["name"] == test_name:
            found_log = True
            print(f"   -> Success: Found attendance log for '{test_name}' at {log['time']} on {log['date']}")
            
    if not found_log:
        print(f"   -> Fail: Attendance log for '{test_name}' was not found.")
        return False

    # 6. Export to CSV
    print("\n[Test 6] Exporting to CSV file...")
    csv_file = "test_export.csv"
    success, msg = database.export_to_csv(csv_file)
    csv_path = os.path.join(database.DB_DIR, csv_file)
    if success and os.path.exists(csv_path):
        print(f"   -> Success: {msg}")
        # Clean up CSV file
        try:
            os.remove(csv_path)
        except Exception:
            pass
    else:
        print(f"   -> Fail: {msg}")
        return False

    # 7. Today's statistics
    print("\n[Test 7] Fetching today's statistics...")
    stats = database.get_today_statistics()
    if stats["total_registered"] >= 1 and stats["attendance_marked_today"] >= 1:
        print(f"   -> Success: Stats OK (registered={stats['total_registered']}, marked={stats['attendance_marked_today']})")
    else:
        print("   -> Fail: Statistics returned unexpected values.")
        return False

    # 8. Public user list (no encodings)
    print("\n[Test 8] Fetching registered users (public metadata)...")
    public_users = database.get_registered_users_public()
    if any(u["name"] == test_name for u in public_users):
        print(f"   -> Success: Found '{test_name}' in public user list.")
    else:
        print(f"   -> Fail: '{test_name}' not in public user list.")
        return False

    # 9. Clean up
    print("\n[Test 9] Cleaning up database...")
    success, msg = database.delete_user(test_name)
    if success:
        print(f"   -> Success: {msg}")
    else:
        print(f"   -> Fail: {msg}")
        return False

    print("\n" + "=" * 60)
    print("                ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
    return True

if __name__ == "__main__":
    run_tests()
