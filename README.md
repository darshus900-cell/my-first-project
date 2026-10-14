# Smart Face Attendance System

A Python-based **Smart Attendance Dashboard** that uses **face recognition** (OpenCV + `face_recognition`) to register users via webcam, verify identity with optional **anti-spoofing liveness detection** (eye-blink tracking), and automatically mark attendance with name, date, and time.

## Features

- **Real-time face detection** and recognition from webcam
- **User registration** — capture face, store 128D encoding + snapshot securely in SQLite
- **Automatic attendance** — marks present once per day (duplicate prevention)
- **Today's Statistics** — registered users, attendance marked today, present/absent counts, recent check-ins
- **Registered User Faces** — gallery of stored faces with names, registration date, and status
- **Attendance logs** with search and date filter
- **CSV export** for attendance records
- **Anti-spoofing** — optional blink-based liveness check
- **Dual interfaces** — modern web dashboard (Flask) or desktop GUI (Tkinter)

### Planned / extensible

- Cloud storage sync
- Admin login & roles
- Analytics dashboard integration
- Advanced anti-spoofing (depth / texture models)

## Project Structure

```
Face Attendence System/
├── main.py           # Entry point (web or gui)
├── gui.py            # Tkinter desktop dashboard
├── web_server.py     # Flask web server + APIs
├── detector.py       # Face detection, recognition, liveness
├── database.py       # SQLite + face image storage
├── test_system.py    # Unit tests
├── templates/        # Web HTML
├── static/           # Web CSS & JavaScript
└── data/             # Database, face images, CSV exports (auto-created)
```

## Requirements

- Python 3.9+
- Webcam
- Windows / macOS / Linux

> **Note:** `dlib` and `face_recognition` require CMake and a C++ compiler on Windows. See [face_recognition installation](https://github.com/ageitgey/face_recognition#installation).

## Installation

### Windows (PowerShell or CMD)

```powershell
cd "d:\Face Attendence System"
py -m pip install -r requirements.txt
```

Or double-click **`install.bat`** in the project folder.

> If `pip` is not recognized, always use **`py -m pip`** instead of `pip`.

### Optional virtual environment

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

## Usage

### Web dashboard (default)

```powershell
cd "d:\Face Attendence System"
python main.py
```

Or double-click **`run.bat`**.

Open **http://127.0.0.1:5000** in your browser.

### Desktop GUI (Tkinter)

```bash
python main.py gui
```

### Run tests

```bash
python test_system.py
```

## How It Works

1. **Register Face** — Enter name, align face in camera, click capture. System stores encoding + photo in `data/`.
2. **Dashboard** — Live feed recognizes registered users. After liveness verification (2 blinks), attendance is logged automatically.
3. **Registered Faces** — View all enrolled users with photos and registration details.
4. **Attendance Logs** — Search, filter by date, export to CSV.

## Configuration

In **System Settings** (web or GUI):

| Setting | Description |
|---------|-------------|
| Camera Index | `0` = default webcam |
| Liveness Check | Require eye blinks before marking attendance |
| Tolerance | Lower = stricter face matching (0.3–0.8) |

## Data Storage

- **SQLite:** `data/attendance.db` — users, encodings, attendance logs
- **Face images:** `data/faces/*.jpg`
- **CSV exports:** `data/attendance_records.csv`

## API Endpoints (Web)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stats` | GET | Today's statistics |
| `/api/users` | GET | Registered users list |
| `/api/users/<name>/photo` | GET | User face image |
| `/api/users/<name>` | DELETE | Remove user |
| `/api/register` | POST | Register new face |
| `/api/attendance` | GET | Attendance logs |
| `/api/export` | GET | Export CSV |

## License

Educational / project use.
