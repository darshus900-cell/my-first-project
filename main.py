import os
import sys

# Ensure the working directory is set to the project root
project_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_dir)
os.chdir(project_dir)

def check_dependencies():
    """Verify that all critical external libraries are present in the environment."""
    required = {
        "numpy": "NumPy",
        "PIL": "Pillow (PIL)",
        "cv2": "OpenCV",
        "dlib": "Dlib",
        "face_recognition": "Face Recognition"
    }
    
    missing = []
    for module_name, display_name in required.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(display_name)
            
    if missing:
        print("\n[CRITICAL ERROR] Missing Required Dependencies:")
        for name in missing:
            print(f" - {name}")
        print("\nPlease run the installation commands specified in the project documentation.")
        sys.exit(1)

def main():
    print("=" * 60)
    print("        SMART FACE ATTENDANCE SYSTEM STARTUP")
    print("=" * 60)
    print("[1/3] Verifying library dependencies...")
    check_dependencies()
    print("      -> All libraries verified!")

    print("[2/3] Initializing local database and filesystems...")
    import database
    database.init_db()
    print("      -> Database initialized successfully!")

    mode = "web"
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ("gui", "desktop", "tk"):
            mode = "gui"
        elif arg in ("web", "browser"):
            mode = "web"

    if mode == "gui":
        print("[3/3] Launching Desktop GUI (Tkinter)...")
        import gui
        gui.database.init_db()
        app = gui.AttendanceApp()
        app.mainloop()
    else:
        print("[3/3] Launching Web Dashboard on http://127.0.0.1:5000 ...")
        print("      Tip: Run 'python main.py gui' for the desktop app.")
        import web_server
        try:
            web_server.start_server(port=5000)
        except Exception as e:
            print(f"\n[FATAL ERROR] Run failed: {str(e)}")
            sys.exit(1)

    print("\nSystem shut down gracefully.")

if __name__ == "__main__":
    main()
