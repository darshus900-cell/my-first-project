import os
import sys
import time
import queue
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
import cv2
from PIL import Image, ImageTk
import database
import detector

class CameraThread(threading.Thread):
    def __init__(self, camera_index, face_detector, check_liveness, tolerance):
        super().__init__()
        self.camera_index = camera_index
        self.detector = face_detector
        self.check_liveness = check_liveness
        self.tolerance = tolerance
        self.frame_queue = queue.Queue(maxsize=2)
        self.running = False
        self.cap = None
        self.last_raw_frame = None
        self.lock = threading.Lock()

    def run(self):
        if sys.platform == "win32":
            self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        else:
            self.cap = cv2.VideoCapture(self.camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if not self.cap.isOpened():
            print(f"[CameraThread] Error: Camera index {self.camera_index} could not be opened.")
            return

        self.running = True
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            # Mirror frame horizontally for natural view
            frame = cv2.flip(frame, 1)

            # Store raw frame thread-safely
            with self.lock:
                self.last_raw_frame = frame.copy()

            # Process frame using the detector
            processed_frame, faces = self.detector.process_frame(
                frame,
                tolerance=self.tolerance,
                check_liveness=self.check_liveness
            )

            # Convert BGR (OpenCV) to RGB (Tkinter/PIL)
            processed_rgb = cv2.cvtColor(processed_frame, cv2.COLOR_BGR2RGB)

            # Push to queue (drop oldest if full to avoid delay)
            if self.frame_queue.full():
                try:
                    self.frame_queue.get_nowait()
                except queue.Empty:
                    pass
            self.frame_queue.put((processed_rgb, faces))
            time.sleep(0.02)  # Limit CPU load (approx 30-40 FPS)

        if self.cap:
            self.cap.release()

    def get_last_raw_frame(self):
        with self.lock:
            return self.last_raw_frame.copy() if self.last_raw_frame is not None else None

    def stop(self):
        self.running = False
        if self.is_alive():
            self.join(timeout=1.0)


class AttendanceApp(tk.Tk):
    def __init__(self):
        super().__init__()

        # Configure window
        self.title("Smart Face Attendance System")
        self.geometry("1100x700")
        self.configure(bg="#121214")
        self.resizable(True, True)

        # Initialize detector and load config
        self.detector = detector.FaceDetector()
        
        # Application Settings (Defaults)
        self.camera_index = 0
        self.tolerance = 0.50
        self.check_liveness = True
        
        self.camera_thread = None
        self.active_tab = "dashboard"
        
        # Success notification track
        self.last_success_name = ""
        self.success_toast_time = 0
        self.attendance_cooldown = {}
        self.attendance_cooldown_sec = 3.0

        # Styles setup
        self.setup_styles()

        # Build UI layout
        self.build_ui()

        # Start Camera
        self.start_camera_thread()

        # Start GUI update loops
        self.update_clock()
        self.poll_camera_queue()

    def setup_styles(self):
        # Configure overall style
        self.style = ttk.Style()
        self.style.theme_use("clam")

        # Palette
        self.bg_dark = "#121214"
        self.bg_card = "#1E1E24"
        self.accent_indigo = "#6366F1"
        self.text_primary = "#FFFFFF"
        self.text_secondary = "#A0A0AB"
        self.emerald_success = "#10B981"
        self.coral_danger = "#EF4444"

        # Treeview styling
        self.style.configure("Treeview",
            background=self.bg_card,
            foreground=self.text_primary,
            rowheight=35,
            fieldbackground=self.bg_card,
            borderwidth=0,
            font=("Segoe UI", 10)
        )
        self.style.map("Treeview",
            background=[("selected", self.accent_indigo)],
            foreground=[("selected", "#FFFFFF")]
        )
        
        self.style.configure("Treeview.Heading",
            background="#27272A",
            foreground=self.text_primary,
            font=("Segoe UI", 10, "bold"),
            borderwidth=0
        )
        
        # Scrollbar styling
        self.style.configure("Vertical.TScrollbar",
            gripcount=0,
            background="#3F3F46",
            troughcolor=self.bg_dark,
            borderwidth=0,
            arrowsize=10
        )

    def build_ui(self):
        # Create Sidebar
        self.sidebar = tk.Frame(self, bg="#18181B", width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # App Logo & Header
        logo_label = tk.Label(
            self.sidebar,
            text="👤 SMART ATTEND",
            fg=self.text_primary,
            bg="#18181B",
            font=("Segoe UI", 14, "bold")
        )
        logo_label.pack(pady=25, padx=10, anchor="w")

        sub_logo = tk.Label(
            self.sidebar,
            text="Face Recognition System",
            fg=self.text_secondary,
            bg="#18181B",
            font=("Segoe UI", 8)
        )
        sub_logo.pack(pady=(0, 20), padx=15, anchor="w")

        # Sidebar Buttons
        self.sidebar_buttons = {}
        tabs = [
            ("dashboard", "📊 Dashboard"),
            ("register", "👤 Register Face"),
            ("faces", "🖼 Registered Faces"),
            ("logs", "🕒 Attendance Logs"),
            ("settings", "⚙️ System Settings")
        ]
        
        for tab_id, label in tabs:
            btn = tk.Button(
                self.sidebar,
                text=label,
                anchor="w",
                fg=self.text_secondary,
                bg="#18181B",
                activeforeground=self.text_primary,
                activebackground=self.bg_card,
                bd=0,
                padx=20,
                pady=12,
                font=("Segoe UI", 11),
                cursor="hand2",
                command=lambda tid=tab_id: self.switch_tab(tid)
            )
            btn.pack(fill="x", padx=10, pady=2)
            
            # Hover effects
            btn.bind("<Enter>", lambda e, b=btn: b.config(fg=self.text_primary, bg="#27272A"))
            btn.bind("<Leave>", lambda e, b=btn: self.restore_btn_style(b))
            self.sidebar_buttons[tab_id] = btn

        # Clock & Info (Sidebar Footer)
        self.clock_frame = tk.Frame(self.sidebar, bg="#18181B")
        self.clock_frame.pack(side="bottom", fill="x", pady=20, padx=15)
        
        self.time_label = tk.Label(
            self.clock_frame,
            text="00:00:00",
            fg=self.text_primary,
            bg="#18181B",
            font=("Segoe UI", 12, "bold")
        )
        self.time_label.pack(anchor="w")

        self.date_label = tk.Label(
            self.clock_frame,
            text="May 22, 2026",
            fg=self.text_secondary,
            bg="#18181B",
            font=("Segoe UI", 9)
        )
        self.date_label.pack(anchor="w")

        # Main Workspace Panel
        self.workspace = tk.Frame(self, bg=self.bg_dark)
        self.workspace.pack(side="right", fill="both", expand=True)

        # Active view container
        self.active_view = None
        self.switch_tab("dashboard")

    def restore_btn_style(self, button):
        for tid, btn in self.sidebar_buttons.items():
            if btn == button:
                if tid == self.active_tab:
                    btn.config(fg=self.text_primary, bg=self.accent_indigo)
                else:
                    btn.config(fg=self.text_secondary, bg="#18181B")

    def switch_tab(self, tab_id):
        self.active_tab = tab_id
        
        # Update sidebar buttons style
        for tid, btn in self.sidebar_buttons.items():
            if tid == tab_id:
                btn.config(fg=self.text_primary, bg=self.accent_indigo)
            else:
                btn.config(fg=self.text_secondary, bg="#18181B")

        # Clear active view
        if self.active_view:
            self.active_view.destroy()

        # Build selected view
        if tab_id == "dashboard":
            self.build_dashboard_view()
        elif tab_id == "register":
            self.build_register_view()
        elif tab_id == "faces":
            self.build_registered_faces_view()
        elif tab_id == "logs":
            self.build_logs_view()
        elif tab_id == "settings":
            self.build_settings_view()

    # --- VIEW BUILDERS ---

    def build_dashboard_view(self):
        self.active_view = tk.Frame(self.workspace, bg=self.bg_dark)
        self.active_view.pack(fill="both", expand=True, padx=25, pady=25)

        # Header Label
        header = tk.Label(
            self.active_view,
            text="System Dashboard",
            fg=self.text_primary,
            bg=self.bg_dark,
            font=("Segoe UI", 16, "bold")
        )
        header.pack(anchor="w", pady=(0, 20))

        # Main Split Frame
        split_frame = tk.Frame(self.active_view, bg=self.bg_dark)
        split_frame.pack(fill="both", expand=True)

        # LEFT FRAME (Webcam View)
        left_frame = tk.Frame(split_frame, bg=self.bg_dark)
        left_frame.pack(side="left", fill="both", expand=True)

        self.video_container = tk.Frame(left_frame, bg="#09090B", bd=1, highlightthickness=1, highlightbackground="#27272A")
        self.video_container.pack(fill="both", expand=True)

        self.video_label = tk.Label(self.video_container, bg="#09090B")
        self.video_label.pack(fill="both", expand=True)

        # Camera Status Overlay Indicator
        self.status_bar = tk.Label(
            left_frame,
            text="Initializing camera stream...",
            fg=self.text_secondary,
            bg=self.bg_dark,
            pady=10,
            font=("Segoe UI", 10)
        )
        self.status_bar.pack(anchor="w")

        # RIGHT FRAME (Info & Controls)
        right_frame = tk.Frame(split_frame, bg=self.bg_dark, width=320)
        right_frame.pack(side="right", fill="y", padx=(20, 0))
        right_frame.pack_propagate(False)

        # Liveness Feedback Card
        liveness_card = tk.LabelFrame(
            right_frame,
            text="🔒 Real-Time Verification",
            fg=self.text_primary,
            bg=self.bg_card,
            bd=0,
            padx=15,
            pady=15,
            font=("Segoe UI", 11, "bold")
        )
        liveness_card.pack(fill="x", pady=(0, 15))

        self.liveness_status_lbl = tk.Label(
            liveness_card,
            text="LIVENESS DETECTOR: ACTIVE",
            fg=self.emerald_success,
            bg=self.bg_card,
            font=("Segoe UI", 10, "bold")
        )
        self.liveness_status_lbl.pack(anchor="w", pady=(0, 5))

        self.liveness_desc_lbl = tk.Label(
            liveness_card,
            text="Scanning faces. Blink twice to verify authenticity and record login.",
            fg=self.text_secondary,
            bg=self.bg_card,
            wraplength=270,
            justify="left",
            font=("Segoe UI", 9)
        )
        self.liveness_desc_lbl.pack(anchor="w")

        # Quick Statistics Card
        stats_card = tk.LabelFrame(
            right_frame,
            text="📈 Today's Statistics",
            fg=self.text_primary,
            bg=self.bg_card,
            bd=0,
            padx=15,
            pady=15,
            font=("Segoe UI", 11, "bold")
        )
        stats_card.pack(fill="x", pady=15)

        self.stat_labels = {}
        stat_items = [
            ("registered", "Total Registered Users: 0"),
            ("marked", "Attendance Marked Today: 0"),
            ("present", "Present Today: 0"),
            ("absent", "Absent Today: 0"),
        ]
        for key, text in stat_items:
            lbl = tk.Label(
                stats_card,
                text=text,
                fg=self.text_primary,
                bg=self.bg_card,
                font=("Segoe UI", 10)
            )
            lbl.pack(anchor="w", pady=2)
            self.stat_labels[key] = lbl

        # Recent Activity Card
        activity_card = tk.LabelFrame(
            right_frame,
            text="🔔 Recent Check-Ins",
            fg=self.text_primary,
            bg=self.bg_card,
            bd=0,
            padx=15,
            pady=15,
            font=("Segoe UI", 11, "bold")
        )
        activity_card.pack(fill="both", expand=True, pady=(15, 0))

        self.recent_listbox = tk.Listbox(
            activity_card,
            bg=self.bg_card,
            fg=self.text_primary,
            bd=0,
            selectbackground=self.accent_indigo,
            highlightthickness=0,
            font=("Segoe UI", 9)
        )
        self.recent_listbox.pack(fill="both", expand=True)

        self.update_stats()

    def build_registered_faces_view(self):
        """Display all stored registered faces with names and registration details."""
        self.active_view = tk.Frame(self.workspace, bg=self.bg_dark)
        self.active_view.pack(fill="both", expand=True, padx=25, pady=25)

        header_frame = tk.Frame(self.active_view, bg=self.bg_dark)
        header_frame.pack(fill="x", pady=(0, 15))

        tk.Label(
            header_frame,
            text="Registered User Faces",
            fg=self.text_primary,
            bg=self.bg_dark,
            font=("Segoe UI", 16, "bold")
        ).pack(side="left")

        search_frame = tk.Frame(header_frame, bg=self.bg_dark)
        search_frame.pack(side="right")

        tk.Label(
            search_frame,
            text="Search:",
            fg=self.text_secondary,
            bg=self.bg_dark,
            font=("Segoe UI", 10)
        ).pack(side="left", padx=5)

        self.faces_search_entry = tk.Entry(
            search_frame,
            bg=self.bg_card,
            fg=self.text_primary,
            insertbackground=self.text_primary,
            bd=0,
            highlightthickness=1,
            highlightbackground="#27272A",
            highlightcolor=self.accent_indigo,
            font=("Segoe UI", 10),
            width=22
        )
        self.faces_search_entry.pack(side="left", padx=5)
        self.faces_search_entry.bind("<KeyRelease>", lambda e: self.filter_registered_faces())

        # Scrollable grid of face cards
        container = tk.Frame(self.active_view, bg=self.bg_card)
        container.pack(fill="both", expand=True)

        self.faces_canvas = tk.Canvas(
            container,
            bg=self.bg_card,
            highlightthickness=0,
            bd=0
        )
        scrollbar = ttk.Scrollbar(container, orient="vertical", style="Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")
        self.faces_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.faces_canvas.yview)

        self.faces_grid_frame = tk.Frame(self.faces_canvas, bg=self.bg_card)
        self.faces_canvas_window = self.faces_canvas.create_window(
            (0, 0), window=self.faces_grid_frame, anchor="nw"
        )
        self.faces_canvas.configure(yscrollcommand=scrollbar.set)
        self.faces_grid_frame.bind(
            "<Configure>",
            lambda e: self.faces_canvas.configure(scrollregion=self.faces_canvas.bbox("all"))
        )
        self.faces_canvas.bind(
            "<Configure>",
            lambda e: self.faces_canvas.itemconfig(self.faces_canvas_window, width=e.width)
        )

        self.reload_registered_faces_grid()

    def build_register_view(self):
        self.active_view = tk.Frame(self.workspace, bg=self.bg_dark)
        self.active_view.pack(fill="both", expand=True, padx=25, pady=25)

        # Header Label
        header = tk.Label(
            self.active_view,
            text="Register New Face",
            fg=self.text_primary,
            bg=self.bg_dark,
            font=("Segoe UI", 16, "bold")
        )
        header.pack(anchor="w", pady=(0, 20))

        # Main Split
        split_frame = tk.Frame(self.active_view, bg=self.bg_dark)
        split_frame.pack(fill="both", expand=True)

        # Left Column: Frame Capture view (so they align their face)
        left_frame = tk.Frame(split_frame, bg=self.bg_dark)
        left_frame.pack(side="left", fill="both", expand=True)

        self.video_container = tk.Frame(left_frame, bg="#09090B", bd=1, highlightthickness=1, highlightbackground="#27272A")
        self.video_container.pack(fill="both", expand=True)

        self.video_label = tk.Label(self.video_container, bg="#09090B")
        self.video_label.pack(fill="both", expand=True)

        # Right Column: Input Box & Instructions
        right_frame = tk.Frame(split_frame, bg=self.bg_dark, width=320)
        right_frame.pack(side="right", fill="y", padx=(20, 0))
        right_frame.pack_propagate(False)

        # Registration Panel Card
        form_card = tk.LabelFrame(
            right_frame,
            text="Registration Details",
            fg=self.text_primary,
            bg=self.bg_card,
            bd=0,
            padx=15,
            pady=15,
            font=("Segoe UI", 11, "bold")
        )
        form_card.pack(fill="x", pady=(0, 15))

        tk.Label(
            form_card,
            text="Employee / Student Name:",
            fg=self.text_secondary,
            bg=self.bg_card,
            font=("Segoe UI", 10)
        ).pack(anchor="w", pady=(0, 5))

        self.name_entry = tk.Entry(
            form_card,
            bg="#27272A",
            fg=self.text_primary,
            insertbackground=self.text_primary,
            bd=0,
            highlightthickness=1,
            highlightbackground="#3F3F46",
            highlightcolor=self.accent_indigo,
            font=("Segoe UI", 11),
            pady=5
        )
        self.name_entry.pack(fill="x", pady=(0, 15))

        # Capture and Register Button
        register_btn = tk.Button(
            form_card,
            text="Capture & Register Face",
            bg=self.accent_indigo,
            fg=self.text_primary,
            activebackground="#4F46E5",
            activeforeground="#FFFFFF",
            bd=0,
            pady=10,
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
            command=self.capture_and_register
        )
        register_btn.pack(fill="x")

        # Instruction Card
        instruction_card = tk.LabelFrame(
            right_frame,
            text="Instructions",
            fg=self.text_primary,
            bg=self.bg_card,
            bd=0,
            padx=15,
            pady=15,
            font=("Segoe UI", 11, "bold")
        )
        instruction_card.pack(fill="both", expand=True)

        instructions = (
            "1. Enter the full name of the person in the box above.\n\n"
            "2. Make sure the face is fully illuminated and visible in the camera preview.\n\n"
            "3. Look directly at the camera without accessories (sunglasses, masks).\n\n"
            "4. Ensure only ONE face is present in the camera view.\n\n"
            "5. Click 'Capture & Register' to save their facial signature to the system database."
        )
        tk.Label(
            instruction_card,
            text=instructions,
            fg=self.text_secondary,
            bg=self.bg_card,
            wraplength=270,
            justify="left",
            font=("Segoe UI", 9),
            pady=5
        ).pack(anchor="nw")

    def build_logs_view(self):
        self.active_view = tk.Frame(self.workspace, bg=self.bg_dark)
        self.active_view.pack(fill="both", expand=True, padx=25, pady=25)

        # Header Frame (for Search and Export Buttons)
        header_frame = tk.Frame(self.active_view, bg=self.bg_dark)
        header_frame.pack(fill="x", pady=(0, 20))

        header = tk.Label(
            header_frame,
            text="Attendance Records",
            fg=self.text_primary,
            bg=self.bg_dark,
            font=("Segoe UI", 16, "bold")
        )
        header.pack(side="left")

        # Export Button
        export_btn = tk.Button(
            header_frame,
            text="📥 Export to CSV",
            bg=self.emerald_success,
            fg=self.text_primary,
            activebackground="#059669",
            activeforeground="#FFFFFF",
            bd=0,
            padx=15,
            pady=6,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            command=self.export_logs
        )
        export_btn.pack(side="right", padx=(10, 0))

        # Search Bar
        search_frame = tk.Frame(header_frame, bg=self.bg_dark)
        search_frame.pack(side="right")

        tk.Label(
            search_frame,
            text="Search:",
            fg=self.text_secondary,
            bg=self.bg_dark,
            font=("Segoe UI", 10)
        ).pack(side="left", padx=5)

        self.search_entry = tk.Entry(
            search_frame,
            bg=self.bg_card,
            fg=self.text_primary,
            insertbackground=self.text_primary,
            bd=0,
            highlightthickness=1,
            highlightbackground="#27272A",
            highlightcolor=self.accent_indigo,
            font=("Segoe UI", 10),
            width=20
        )
        self.search_entry.pack(side="left", padx=5)
        self.search_entry.bind("<KeyRelease>", lambda e: self.filter_logs())

        # Table Container
        table_container = tk.Frame(self.active_view, bg=self.bg_card)
        table_container.pack(fill="both", expand=True)

        # Treeview Scrollbar
        scrollbar = ttk.Scrollbar(table_container, orient="vertical", style="Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")

        # Treeview Tree
        self.logs_tree = ttk.Treeview(
            table_container,
            columns=("name", "registered", "date", "time", "method", "status"),
            show="headings",
            yscrollcommand=scrollbar.set
        )
        self.logs_tree.pack(fill="both", expand=True)
        scrollbar.config(command=self.logs_tree.yview)

        self.logs_tree.heading("name", text="Employee Name", anchor="w")
        self.logs_tree.heading("registered", text="Registered On", anchor="center")
        self.logs_tree.heading("date", text="Date", anchor="center")
        self.logs_tree.heading("time", text="Login Time", anchor="center")
        self.logs_tree.heading("method", text="Check-In", anchor="center")
        self.logs_tree.heading("status", text="Status", anchor="center")

        self.logs_tree.column("name", width=140, anchor="w")
        self.logs_tree.column("registered", width=130, anchor="center")
        self.logs_tree.column("date", width=100, anchor="center")
        self.logs_tree.column("time", width=90, anchor="center")
        self.logs_tree.column("method", width=120, anchor="center")
        self.logs_tree.column("status", width=90, anchor="center")

        self.reload_logs_table()

    def build_settings_view(self):
        self.active_view = tk.Frame(self.workspace, bg=self.bg_dark)
        self.active_view.pack(fill="both", expand=True, padx=25, pady=25)

        # Header Label
        header = tk.Label(
            self.active_view,
            text="System Settings",
            fg=self.text_primary,
            bg=self.bg_dark,
            font=("Segoe UI", 16, "bold")
        )
        header.pack(anchor="w", pady=(0, 20))

        # Main Settings Container Card
        settings_card = tk.LabelFrame(
            self.active_view,
            text="Configure Recognition Parameters",
            fg=self.text_primary,
            bg=self.bg_card,
            bd=0,
            padx=20,
            pady=20,
            font=("Segoe UI", 11, "bold")
        )
        settings_card.pack(fill="both", expand=True)

        # Camera Index Option
        tk.Label(
            settings_card,
            text="Camera Source Index:",
            fg=self.text_secondary,
            bg=self.bg_card,
            font=("Segoe UI", 10)
        ).grid(row=0, column=0, sticky="w", pady=10)

        self.cam_index_var = tk.StringVar(value=str(self.camera_index))
        cam_dropdown = ttk.Combobox(
            settings_card,
            textvariable=self.cam_index_var,
            values=["0", "1", "2", "3"],
            width=10,
            state="readonly"
        )
        cam_dropdown.grid(row=0, column=1, sticky="w", padx=20, pady=10)

        # Liveness Detection Toggle
        tk.Label(
            settings_card,
            text="Anti-Spoofing (Liveness Check):",
            fg=self.text_secondary,
            bg=self.bg_card,
            font=("Segoe UI", 10)
        ).grid(row=1, column=0, sticky="w", pady=10)

        self.liveness_var = tk.BooleanVar(value=self.check_liveness)
        liveness_cb = tk.Checkbutton(
            settings_card,
            variable=self.liveness_var,
            bg=self.bg_card,
            activebackground=self.bg_card,
            activeforeground=self.text_primary,
            bd=0,
            selectcolor="#27272A",
            text="Require eyes blinking"
        )
        liveness_cb.grid(row=1, column=1, sticky="w", padx=20, pady=10)

        # Tolerance / Strictness Slider
        tk.Label(
            settings_card,
            text="Face Distance Tolerance (Strictness):",
            fg=self.text_secondary,
            bg=self.bg_card,
            font=("Segoe UI", 10)
        ).grid(row=2, column=0, sticky="w", pady=10)

        slider_frame = tk.Frame(settings_card, bg=self.bg_card)
        slider_frame.grid(row=2, column=1, sticky="w", padx=20, pady=10)

        self.tolerance_var = tk.DoubleVar(value=self.tolerance)
        tolerance_slider = tk.Scale(
            slider_frame,
            from_=0.3,
            to=0.8,
            resolution=0.05,
            orient="horizontal",
            variable=self.tolerance_var,
            bg=self.bg_card,
            fg=self.text_primary,
            bd=0,
            highlightthickness=0,
            length=180
        )
        tolerance_slider.pack(side="left")
        
        tk.Label(
            slider_frame,
            text="(Lower is stricter)",
            fg=self.text_secondary,
            bg=self.bg_card,
            font=("Segoe UI", 8, "italic")
        ).pack(side="left", padx=5)

        # Save Button
        save_btn = tk.Button(
            settings_card,
            text="Save Settings",
            bg=self.accent_indigo,
            fg=self.text_primary,
            activebackground="#4F46E5",
            activeforeground="#FFFFFF",
            bd=0,
            padx=20,
            pady=8,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            command=self.save_settings
        )
        save_btn.grid(row=3, column=0, columnspan=2, sticky="w", pady=25)

    # --- FUNCTIONALITY IMPLEMENTATIONS ---

    def start_camera_thread(self):
        """Stop existing thread and start a new one with current settings."""
        self.stop_camera_thread()

        self.camera_thread = CameraThread(
            camera_index=self.camera_index,
            face_detector=self.detector,
            check_liveness=self.check_liveness,
            tolerance=self.tolerance
        )
        self.camera_thread.start()

    def stop_camera_thread(self):
        if self.camera_thread:
            self.camera_thread.stop()
            self.camera_thread = None

    def poll_camera_queue(self):
        """Fetch frame from queue and display it on active views."""
        if self.camera_thread and self.camera_thread.running:
            try:
                # Fetch without blocking
                rgb_frame, recognized_faces = self.camera_thread.frame_queue.get_nowait()
                
                now_ts = time.time()
                for face in recognized_faces:
                    name = face["name"]
                    if name == "Unknown":
                        continue

                    last_mark = self.attendance_cooldown.get(name, 0)
                    if now_ts - last_mark < self.attendance_cooldown_sec:
                        continue

                    marked, msg = database.mark_attendance(name, method="Face Recognition")
                    if marked:
                        self.attendance_cooldown[name] = now_ts
                        print(f"[Attendance] {msg}")
                        self.last_success_name = name
                        self.success_toast_time = now_ts
                        self.update_stats()
                        if self.active_tab == "logs":
                            self.reload_logs_table()

                # Process raw frame image to PIL PhotoImage
                height, width, _ = rgb_frame.shape
                
                # Calculate resize factor to fit frame containers beautifully
                # Keep aspect ratio
                container_width = self.video_container.winfo_width()
                container_height = self.video_container.winfo_height()
                
                if container_width > 10 and container_height > 10:
                    scale = min(container_width / width, container_height / height)
                    new_w = int(width * scale)
                    new_h = int(height * scale)
                    
                    img = Image.fromarray(rgb_frame)
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    
                    img_tk = ImageTk.PhotoImage(image=img)
                    
                    # Update label in Active tab (both dashboard and register have self.video_label)
                    if hasattr(self, "video_label") and self.video_label.winfo_exists():
                        self.video_label.img_tk = img_tk
                        self.video_label.config(image=img_tk)

                # Visual Toast Overlay: Display "Attendance Marked Successfully"
                if self.active_tab == "dashboard" and hasattr(self, "status_bar"):
                    if time.time() - self.success_toast_time < 3.0:
                        self.status_bar.config(
                            text=f"✅ Attendance marked for {self.last_success_name} successfully!",
                            fg=self.emerald_success
                        )
                    else:
                        self.status_bar.config(
                            text="Scanning... Position your face in front of the camera.",
                            fg=self.text_secondary
                        )

            except queue.Empty:
                pass

        # Schedule next loop iteration
        self.after(20, self.poll_camera_queue)

    def capture_and_register(self):
        """Capture the current frame, detect exactly one face, get encoding, and register it."""
        if not self.camera_thread:
            messagebox.showerror("Error", "Camera stream is offline.")
            return

        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("Warning", "Please enter a name for registration.")
            return

        face_encoding = None
        face_crop = None
        last_error = "Camera not ready. Wait a few seconds and try again."

        for _ in range(15):
            raw_frame = self.camera_thread.get_last_raw_frame()
            if raw_frame is None:
                time.sleep(0.15)
                continue

            enc, _loc, crop, err = detector.extract_face_for_registration(raw_frame)
            if enc is not None:
                face_encoding = enc
                face_crop = crop
                break
            last_error = err or last_error
            time.sleep(0.1)

        if face_encoding is None:
            messagebox.showwarning("Registration Failed", last_error)
            return

        success, msg = database.register_user(name, face_encoding, face_image_bgr=face_crop)
        if success:
            messagebox.showinfo("Success", msg)
            self.name_entry.delete(0, tk.END)
            self.detector.reload_known_faces()
            self.update_stats()
            self.reload_logs_table()
            if hasattr(self, "faces_grid_frame"):
                self.reload_registered_faces_grid()
        else:
            messagebox.showerror("Error", msg)

    def reload_logs_table(self, logs=None):
        if not hasattr(self, "logs_tree") or not self.logs_tree.winfo_exists():
            return

        # Clear existing rows
        for item in self.logs_tree.get_children():
            self.logs_tree.delete(item)

        # Fetch records
        if logs is None:
            logs = database.get_attendance_records()

        # Insert records into table view
        for index, log in enumerate(logs):
            tag = "even" if index % 2 == 0 else "odd"
            self.logs_tree.insert(
                "",
                "end",
                values=(
                    log["name"],
                    log.get("registered_at", "—"),
                    log["date"],
                    log["time"],
                    log.get("check_in_method", "—"),
                    log.get("status", "—"),
                ),
                tags=(tag,)
            )
            
        self.logs_tree.tag_configure("even", background="#1E1E24")
        self.logs_tree.tag_configure("odd", background="#121214")

    def filter_logs(self):
        query = self.search_entry.get().lower().strip()
        all_logs = database.get_attendance_records()
        
        if not query:
            self.reload_logs_table(all_logs)
            return

        filtered = [l for l in all_logs if query in l["name"].lower() or query in l["date"]]
        self.reload_logs_table(filtered)

    def export_logs(self):
        success, msg = database.export_to_csv()
        if success:
            messagebox.showinfo("Export Successful", msg)
        else:
            messagebox.showerror("Export Failed", msg)

    def save_settings(self):
        try:
            new_cam_idx = int(self.cam_index_var.get())
            new_tolerance = self.tolerance_var.get()
            new_liveness = self.liveness_var.get()
            
            # Save to class attributes
            self.camera_index = new_cam_idx
            self.tolerance = new_tolerance
            self.check_liveness = new_liveness
            
            # Restart camera thread
            self.start_camera_thread()
            
            messagebox.showinfo("Settings Saved", "System configuration updated and camera restarted successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Could not apply settings: {str(e)}")

    def reload_registered_faces_grid(self, users=None):
        """Populate the registered faces grid with user cards."""
        if not hasattr(self, "faces_grid_frame"):
            return

        for widget in self.faces_grid_frame.winfo_children():
            widget.destroy()

        if users is None:
            users = database.get_registered_users_public()

        if not users:
            tk.Label(
                self.faces_grid_frame,
                text="No registered faces yet. Use 'Register Face' to add users.",
                fg=self.text_secondary,
                bg=self.bg_card,
                font=("Segoe UI", 11),
                pady=40
            ).grid(row=0, column=0, padx=20, pady=20)
            return

        cols = 3
        for idx, user in enumerate(users):
            row, col = divmod(idx, cols)
            card = tk.Frame(
                self.faces_grid_frame,
                bg="#27272A",
                padx=12,
                pady=12,
                highlightthickness=1,
                highlightbackground="#3F3F46"
            )
            card.grid(row=row, column=col, padx=12, pady=12, sticky="n")

            img_path = None
            if user.get("face_image_path"):
                img_path = os.path.join(database.DB_DIR, user["face_image_path"])

            if img_path and os.path.exists(img_path):
                img = Image.open(img_path)
                img = img.resize((120, 120), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                img_lbl = tk.Label(card, image=photo, bg="#27272A")
                img_lbl.image = photo
                img_lbl.pack(pady=(0, 8))
            else:
                tk.Label(
                    card,
                    text="👤",
                    fg=self.text_secondary,
                    bg="#27272A",
                    font=("Segoe UI", 48)
                ).pack(pady=(10, 8))

            status = "Present Today" if user.get("present_today") else "Not Checked In"
            status_color = self.emerald_success if user.get("present_today") else self.text_secondary

            tk.Label(
                card,
                text=user["name"],
                fg=self.text_primary,
                bg="#27272A",
                font=("Segoe UI", 11, "bold")
            ).pack()

            tk.Label(
                card,
                text=f"Registered: {user['created_at']}",
                fg=self.text_secondary,
                bg="#27272A",
                font=("Segoe UI", 8)
            ).pack(pady=(2, 4))

            tk.Label(
                card,
                text=status,
                fg=status_color,
                bg="#27272A",
                font=("Segoe UI", 9, "bold")
            ).pack(pady=(0, 8))

            tk.Button(
                card,
                text="Delete",
                bg=self.coral_danger,
                fg=self.text_primary,
                activebackground="#DC2626",
                bd=0,
                font=("Segoe UI", 9),
                cursor="hand2",
                command=lambda n=user["name"]: self.delete_registered_user(n)
            ).pack()

    def filter_registered_faces(self):
        query = self.faces_search_entry.get().lower().strip()
        users = database.get_registered_users_public()
        if query:
            users = [u for u in users if query in u["name"].lower()]
        self.reload_registered_faces_grid(users)

    def delete_registered_user(self, name):
        if messagebox.askyesno("Confirm Delete", f"Remove '{name}' from the system?"):
            success, msg = database.delete_user(name)
            if success:
                self.detector.reload_known_faces()
                self.reload_registered_faces_grid()
                self.update_stats()
                messagebox.showinfo("Deleted", msg)
            else:
                messagebox.showerror("Error", msg)

    def update_stats(self):
        """Update dashboard metrics and quick activity list."""
        stats = database.get_today_statistics()

        if hasattr(self, "stat_labels"):
            labels_map = {
                "registered": f"Total Registered Users: {stats['total_registered']}",
                "marked": f"Attendance Marked Today: {stats['attendance_marked_today']}",
                "present": f"Present Today: {stats['present_today']}",
                "absent": f"Absent Today: {stats['absent_today']}",
            }
            for key, text in labels_map.items():
                if key in self.stat_labels and self.stat_labels[key].winfo_exists():
                    self.stat_labels[key].config(text=text)

        if hasattr(self, "recent_listbox") and self.recent_listbox.winfo_exists():
            self.recent_listbox.delete(0, tk.END)
            for log in stats["recent_checkins"]:
                self.recent_listbox.insert(tk.END, f" 🟢 {log['time']} - {log['name']}")

        if self.active_tab == "faces" and hasattr(self, "faces_grid_frame"):
            self.reload_registered_faces_grid()

    def update_clock(self):
        """Update clock labels in the sidebar."""
        now = datetime.now()
        time_str = now.strftime("%H:%M:%S")
        date_str = now.strftime("%B %d, %Y")
        
        if hasattr(self, "time_label") and self.time_label.winfo_exists():
            self.time_label.config(text=time_str)
        if hasattr(self, "date_label") and self.date_label.winfo_exists():
            self.date_label.config(text=date_str)
            
        self.after(1000, self.update_clock)

    def destroy(self):
        """Gracefully stop camera thread before closing window."""
        self.stop_camera_thread()
        super().destroy()


if __name__ == "__main__":
    database.init_db()
    app = AttendanceApp()
    app.mainloop()
