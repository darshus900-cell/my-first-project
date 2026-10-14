import time
import cv2
import numpy as np
import face_recognition
import database

# Constants for liveness detection
EAR_THRESHOLD = 0.20  # Eye Aspect Ratio threshold below which eye is considered closed
EAR_CONSEC_FRAMES = 2  # Number of consecutive frames the eye must be closed to register a blink
REQUIRED_BLINKS = 2    # Number of blinks required to verify liveness
SESSION_TIMEOUT = 3.0  # Seconds of absence before tracking session is reset

def calculate_ear(eye_landmarks):
    """
    Calculate Eye Aspect Ratio (EAR) given 6 eye landmark coordinates.
    Formula: EAR = (||p2-p6|| + ||p3-p5||) / (2 * ||p1-p4||)
    """
    # Landmarks are tuples (x, y)
    p = np.array(eye_landmarks)
    
    # Vertical distances
    a = np.linalg.norm(p[1] - p[5])
    b = np.linalg.norm(p[2] - p[4])
    
    # Horizontal distance
    c = np.linalg.norm(p[0] - p[3])
    
    # Avoid division by zero
    if c == 0:
        return 0.0
        
    ear = (a + b) / (2.0 * c)
    return ear

class FaceDetector:
    def __init__(self):
        self.known_face_encodings = []
        self.known_face_names = []
        self.active_sessions = {}  # name -> {consec_frames, blink_count, last_seen, verified, ears}
        self.reload_known_faces()
        
    def reload_known_faces(self):
        """Reload registered faces from the SQLite database."""
        users = database.get_all_users()
        self.known_face_encodings = [u["encoding"] for u in users]
        self.known_face_names = [u["name"] for u in users]
        print(f"Loaded {len(self.known_face_names)} registered faces.")

    def process_frame(self, frame, tolerance=0.5, check_liveness=True):
        """
        Process a BGR frame from OpenCV camera.
        Detects faces, recognizes them, computes EAR, and updates liveness tracking.
        
        Returns:
            processed_frame: BGR frame with visual overlays (boxes, names, blink counts).
            recognized_faces: List of dicts representing recognized/tracked faces with status.
        """
        current_time = time.time()
        
        # Clean up stale sessions
        for name in list(self.active_sessions.keys()):
            if current_time - self.active_sessions[name]["last_seen"] > SESSION_TIMEOUT:
                del self.active_sessions[name]

        # Convert BGR to RGB (face_recognition expects RGB)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Find all face locations and encodings in the current frame
        # We use HOG model for fast CPU processing
        face_locations = face_recognition.face_locations(rgb_frame, model="hog")
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
        
        # Find landmarks for eye blink detection
        face_landmarks_list = []
        if check_liveness and len(face_locations) > 0:
            face_landmarks_list = face_recognition.face_landmarks(rgb_frame, face_locations)

        recognized_faces = []
        
        # Loop through each face found
        for i, (top, right, bottom, left) in enumerate(face_locations):
            face_encoding = face_encodings[i]
            
            # Default identity is Unknown
            name = "Unknown"
            match_index = -1
            
            if len(self.known_face_encodings) > 0:
                # Compare face with database faces
                matches = face_recognition.compare_faces(self.known_face_encodings, face_encoding, tolerance=tolerance)
                face_distances = face_recognition.face_distance(self.known_face_encodings, face_encoding)
                
                if True in matches:
                    match_index = np.argmin(face_distances)
                    if matches[match_index]:
                        name = self.known_face_names[match_index]

            # Liveness detection details
            ear = 0.0
            blink_count = 0
            is_live = False
            consec_frames = 0
            
            # Process liveness if name is known and landmarks exist
            if check_liveness and name != "Unknown" and i < len(face_landmarks_list):
                landmarks = face_landmarks_list[i]
                left_eye = landmarks.get("left_eye", [])
                right_eye = landmarks.get("right_eye", [])
                
                if left_eye and right_eye:
                    left_ear = calculate_ear(left_eye)
                    right_ear = calculate_ear(right_eye)
                    ear = (left_ear + right_ear) / 2.0
                    
                    # Update or create session for this user
                    if name not in self.active_sessions:
                        self.active_sessions[name] = {
                            "consec_frames": 0,
                            "blink_count": 0,
                            "last_seen": current_time,
                            "verified": False,
                            "ear_history": []
                        }
                    
                    session = self.active_sessions[name]
                    session["last_seen"] = current_time
                    
                    # Blink detection state machine
                    if ear < EAR_THRESHOLD:
                        session["consec_frames"] += 1
                    else:
                        if session["consec_frames"] >= EAR_CONSEC_FRAMES:
                            session["blink_count"] += 1
                            print(f"[Liveness] Blink detected for {name}. Total: {session['blink_count']}")
                        session["consec_frames"] = 0
                        
                    # Check if required blinks met
                    if session["blink_count"] >= REQUIRED_BLINKS:
                        session["verified"] = True
                        
                    blink_count = session["blink_count"]
                    is_live = session["verified"]
                    consec_frames = session["consec_frames"]

            # Save tracking metadata
            face_data = {
                "name": name,
                "box": (top, right, bottom, left),
                "ear": ear,
                "blink_count": blink_count,
                "is_live": is_live,
                "session_active": name in self.active_sessions
            }
            recognized_faces.append(face_data)
            
            # Render overlays on the BGR frame
            # Use color-coding: Green for verified, Indigo for scanning/unknown, Red for error
            if name == "Unknown":
                color = (241, 102, 99)  # Coral/Red (BGR: B=99, G=102, R=241) -> OpenCV uses BGR
                box_color = (99, 102, 241)  # Indigo
                label = "Unknown - Register First"
            elif not check_liveness:
                box_color = (129, 185, 16)  # Green
                label = name
            else:
                if is_live:
                    box_color = (129, 185, 16)  # Emerald Green
                    label = f"{name} (Verified)"
                else:
                    box_color = (241, 102, 99)  # Orange/Red (liveness pending)
                    label = f"{name} (Blinks: {blink_count}/{REQUIRED_BLINKS})"

            # Draw bounding box
            cv2.rectangle(frame, (left, top), (right, bottom), box_color, 2)
            
            # Draw tag box
            cv2.rectangle(frame, (left, bottom - 30), (right, bottom), box_color, cv2.FILLED)
            font = cv2.FONT_HERSHEY_DUPLEX
            cv2.putText(frame, label, (left + 6, bottom - 8), font, 0.5, (255, 255, 255), 1)
            
            # Draw eye aspect ratio indicator if scanning
            if check_liveness and name != "Unknown":
                cv2.putText(
                    frame,
                    f"EAR: {ear:.2f}",
                    (left + 6, top - 10),
                    font,
                    0.4,
                    (255, 255, 255) if ear >= EAR_THRESHOLD else (0, 0, 255),
                    1
                )

        return frame, recognized_faces


def extract_face_for_registration(frame_bgr):
    """
    Robustly detect one face and return encoding + location + crop for registration.
    Tries multiple detection passes (resize, upsample) for reliability outside IDE.
    Returns (encoding, face_location, face_crop) or (None, None, None) with error message.
    """
    if frame_bgr is None or frame_bgr.size == 0:
        return None, None, None, "No camera frame available."

    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]

    # Downscale very large frames — HOG works better on moderate sizes
    scale = 1.0
    if max(h, w) > 960:
        scale = 960 / max(h, w)
        rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))

    face_locations = []
    for upsample in (1, 2, 0):
        face_locations = face_recognition.face_locations(
            rgb, model="hog", number_of_times_to_upsample=upsample
        )
        if len(face_locations) == 1:
            break
        if len(face_locations) > 1 and upsample == 0:
            return None, None, None, "Multiple faces detected. Only ONE student in camera view."

    if len(face_locations) == 0:
        return None, None, None, (
            "No face detected. Face the camera directly, use good lighting, and try again."
        )
    if len(face_locations) > 1:
        return None, None, None, "Multiple faces detected. Only ONE student in camera view."

    top, right, bottom, left = face_locations[0]

    # Map box back to original frame coordinates if scaled
    if scale != 1.0:
        inv = 1.0 / scale
        top = int(top * inv)
        right = int(right * inv)
        bottom = int(bottom * inv)
        left = int(left * inv)
        face_locations = [(top, right, bottom, left)]
        rgb_full = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    else:
        rgb_full = rgb

    try:
        face_encodings = face_recognition.face_encodings(
            rgb_full, face_locations, num_jitters=2, model="small"
        )
    except TypeError:
        face_encodings = face_recognition.face_encodings(
            rgb_full, face_locations, num_jitters=2
        )
    if not face_encodings:
        face_encodings = face_recognition.face_encodings(rgb_full, face_locations, num_jitters=1)

    if not face_encodings:
        return None, None, None, "Could not read face data. Move closer to the camera and retry."

    face_crop = crop_face_from_frame(frame_bgr, face_locations[0])
    return face_encodings[0], face_locations[0], face_crop, None


def crop_face_from_frame(frame_bgr, face_location, padding=20):
    """
    Crop a face region from a BGR frame given (top, right, bottom, left).
    Returns cropped BGR image or None if invalid.
    """
    top, right, bottom, left = face_location
    h, w = frame_bgr.shape[:2]
    top = max(0, top - padding)
    left = max(0, left - padding)
    bottom = min(h, bottom + padding)
    right = min(w, right + padding)
    if bottom <= top or right <= left:
        return None
    return frame_bgr[top:bottom, left:right].copy()
