import os
import sys
import time
import json
import threading
import cv2
import numpy as np
from flask import Flask, render_template, Response, request, jsonify, send_from_directory
import database
import detector

app = Flask(__name__)

# Core global variables
face_detector = None
camera_thread = None
system_settings = {
    "camera_index": 0,
    "tolerance": 0.50,
    "check_liveness": True
}

class WebCameraThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.detector = None
        self.running = False
        self.cap = None
        
        # Thread-safe buffers
        self.lock = threading.Lock()
        self.latest_jpeg = None
        self.latest_raw = None
        self.frame_buffer = []
        self.max_buffer = 15
        self.camera_ready = False
        self.status_msg = "Scanner ready"
        self.success_toast = ""
        self.success_time = 0
        self.mark_cooldown = {}
        self.mark_cooldown_sec = 3.0

    def run(self):
        global face_detector, system_settings
        self.detector = face_detector
        
        cam_idx = system_settings["camera_index"]
        print(f"[WebCameraThread] Opening camera index {cam_idx}...")
        if sys.platform == "win32":
            self.cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)
        else:
            self.cap = cv2.VideoCapture(cam_idx)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        if not self.cap.isOpened():
            print(f"[WebCameraThread] Error: Camera {cam_idx} could not be opened.")
            self.status_msg = f"Error: Camera index {cam_idx} could not be opened."
            return

        self.running = True
        self.status_msg = "Webcam streaming active"

        for _ in range(30):
            ret, frame = self.cap.read()
            if ret:
                frame = cv2.flip(frame, 1)
                with self.lock:
                    self.latest_raw = frame.copy()
                    self.frame_buffer.append(frame.copy())
                    if len(self.frame_buffer) > self.max_buffer:
                        self.frame_buffer.pop(0)
        self.camera_ready = self.latest_raw is not None

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            # Mirror frame horizontally for natural view
            frame = cv2.flip(frame, 1)

            # Keep a raw copy thread-safely
            with self.lock:
                self.latest_raw = frame.copy()
                self.frame_buffer.append(frame.copy())
                if len(self.frame_buffer) > self.max_buffer:
                    self.frame_buffer.pop(0)
                self.camera_ready = True

            # Process frame with face matching & liveness checks
            processed_frame, faces = self.detector.process_frame(
                frame,
                tolerance=system_settings["tolerance"],
                check_liveness=system_settings["check_liveness"]
            )

            # Auto-mark attendance when a registered face is recognized
            now_ts = time.time()
            for face in faces:
                name = face["name"]
                if name == "Unknown":
                    continue

                last_mark = self.mark_cooldown.get(name, 0)
                if now_ts - last_mark < self.mark_cooldown_sec:
                    continue

                marked, msg = database.mark_attendance(name, method="Face Recognition")
                if marked:
                    self.mark_cooldown[name] = now_ts
                    print(f"[WebAttendance] {msg}")
                    with self.lock:
                        self.success_toast = name
                        self.success_time = now_ts

            # Render custom text if attendance was recently logged
            if time.time() - self.success_time < 3.0:
                cv2.putText(
                    processed_frame,
                    f"SUCCESS: {self.success_toast} marked present",
                    (15, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (81, 185, 16),  # Emerald Green
                    2
                )

            # Encode frame to JPEG
            ret, jpeg_buffer = cv2.imencode('.jpg', processed_frame)
            if ret:
                with self.lock:
                    self.latest_jpeg = jpeg_buffer.tobytes()
                    
            time.sleep(0.03)  # Match ~30fps

        if self.cap:
            self.cap.release()

    def get_frame(self):
        with self.lock:
            return self.latest_jpeg

    def get_raw_frame(self):
        with self.lock:
            return self.latest_raw.copy() if self.latest_raw is not None else None

    def get_frames_for_registration(self):
        """Return recent frames (newest first) for reliable registration capture."""
        with self.lock:
            if self.frame_buffer:
                return [f.copy() for f in reversed(self.frame_buffer)]
            if self.latest_raw is not None:
                return [self.latest_raw.copy()]
            return []

    def stop(self):
        self.running = False
        self.join(timeout=1.0)


# --- FLASK ENDPOINTS ---

@app.route("/")
def index():
    return render_template("index.html")

def generate_stream():
    """Generates MJPEG stream of camera frames."""
    global camera_thread
    while True:
        if camera_thread and camera_thread.running:
            frame_bytes = camera_thread.get_frame()
            if frame_bytes:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.03)

@app.route("/video_feed")
def video_feed():
    return Response(
        generate_stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

@app.route("/api/attendance")
def api_attendance():
    """Fetch attendance records — all registered users with their log details."""
    date_filter = request.args.get("date") or None
    records = database.get_attendance_records(date_filter=date_filter)
    return jsonify(records)

@app.route("/api/stats")
def api_stats():
    """Fetch current system statistics."""
    return jsonify(database.get_today_statistics())


@app.route("/api/users")
def api_users():
    """Return all registered users with metadata (no encodings)."""
    return jsonify(database.get_registered_users_public())


@app.route("/api/users/<path:name>/photo")
def api_user_photo(name):
    """Serve a registered user's face snapshot image."""
    img_path = database.get_face_image_path(name)
    if img_path and os.path.exists(img_path):
        directory = os.path.dirname(img_path)
        filename = os.path.basename(img_path)
        return send_from_directory(directory, filename)
    return jsonify({"error": "Image not found"}), 404


@app.route("/api/users/<path:name>", methods=["DELETE"])
def api_delete_user(name):
    """Remove a registered user."""
    success, msg = database.delete_user(name)
    if success:
        face_detector.reload_known_faces()
        return jsonify({"success": True, "message": msg})
    return jsonify({"success": False, "message": msg}), 400

@app.route("/api/register", methods=["POST"])
def api_register():
    """Register face from latest raw frame."""
    global camera_thread, face_detector
    
    data = request.json or {}
    name = data.get("name", "").strip()
    
    if not name:
        return jsonify({"success": False, "message": "Please enter a valid name."}), 400
        
    if not camera_thread or not camera_thread.running:
        return jsonify({
            "success": False,
            "message": "Camera is offline. Wait a few seconds or check camera index in Settings.",
        }), 503

    if not camera_thread.camera_ready:
        time.sleep(0.5)

    frames = camera_thread.get_frames_for_registration()
    if not frames:
        return jsonify({
            "success": False,
            "message": "Camera not ready. Wait 3 seconds with face in view, then try again.",
        }), 503

    face_encoding = None
    face_crop = None
    last_error = "Could not detect face."

    for frame in frames:
        enc, loc, crop, err = detector.extract_face_for_registration(frame)
        if enc is not None:
            face_encoding = enc
            face_crop = crop
            break
        last_error = err or last_error

    if face_encoding is None:
        return jsonify({"success": False, "message": last_error}), 400

    success, msg = database.register_user(name, face_encoding, face_image_bgr=face_crop)
    if success:
        face_detector.reload_known_faces()
        users = database.get_registered_users_public()
        records = database.get_attendance_records()
        return jsonify({
            "success": True,
            "message": msg,
            "total_registered": len(users),
            "user": next((u for u in users if u["name"].lower() == name.lower()), None),
        })
    return jsonify({"success": False, "message": msg}), 500

@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """Retrieve or modify configurations."""
    global system_settings, camera_thread
    
    if request.method == "POST":
        data = request.json or {}
        try:
            cam_idx = int(data.get("camera_index", system_settings["camera_index"]))
            tol = float(data.get("tolerance", system_settings["tolerance"]))
            liveness = bool(data.get("check_liveness", system_settings["check_liveness"]))
            
            restart_cam = cam_idx != system_settings["camera_index"]
            
            system_settings["camera_index"] = cam_idx
            system_settings["tolerance"] = tol
            system_settings["check_liveness"] = liveness
            
            if restart_cam:
                print("[WebSettings] Camera index changed. Restarting thread...")
                camera_thread.stop()
                camera_thread = WebCameraThread()
                camera_thread.start()
                
            return jsonify({"success": True, "message": "Settings updated successfully."})
        except Exception as e:
            return jsonify({"success": False, "message": f"Invalid settings: {str(e)}"}), 400
            
    return jsonify(system_settings)

@app.route("/api/export")
def api_export():
    """Export attendance database to CSV."""
    success, msg = database.export_to_csv()
    if success:
        return jsonify({"success": True, "message": msg})
    return jsonify({"success": False, "message": msg}), 500

@app.route("/api/download_csv")
def download_csv():
    """Download exported CSV directly."""
    csv_filename = "attendance_records.csv"
    csv_dir = database.DB_DIR
    return send_from_directory(csv_dir, csv_filename, as_attachment=True)


def start_server(port=5000):
    global face_detector, camera_thread
    
    # Initialize DB
    database.init_db()
    
    # Load face detector
    face_detector = detector.FaceDetector()
    
    # Start background capture thread
    camera_thread = WebCameraThread()
    camera_thread.start()
    
    # Launch Flask
    try:
        print(f"[WebServer] Running on http://127.0.0.1:{port}")
        app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
    finally:
        # Shutdown cleanly
        print("[WebServer] Stopping background threads...")
        if camera_thread:
            camera_thread.stop()
