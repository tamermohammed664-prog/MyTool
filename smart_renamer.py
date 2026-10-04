import os
import re
import json
import hmac
import math
import cv2
import queue
import shutil
import threading
import numpy as np
import pymupdf as fitz
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import easyocr

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_BACKGROUND = "#0F172A"
CARD_BACKGROUND = "#1E293B"
SECONDARY_BUTTON = "#334155"
SECONDARY_HOVER = "#475569"
PRIMARY_BUTTON = "#2563EB"
PRIMARY_HOVER = "#1D4ED8"
FOOTER_BACKGROUND = "#1E293B"
TEXT_PRIMARY = "#F1F5F9"
TEXT_SECONDARY = "#94A3B8"
LOGO_WHITE = "#0F172A"
LOGO_BLUE = "#334155"

DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
DOCUMENT_NUMBER_LENGTH = 8
DEFAULT_ADMIN_PASSWORD = "admin123"
DEFAULT_FIELD_ROIS = (
    (0.32, 0.02, 0.60, 0.075),
    (0.82, 0.245, 0.91, 0.28),
    (0.62, 0.29, 0.98, 0.37),
)


def aggregate_roi_samples(samples):
    try:
        sample_array = np.asarray(samples, dtype=np.float64)
    except ValueError as ex:
        raise ValueError("Each calibration sample must contain the same number of valid ROIs.") from ex
    if (
        sample_array.ndim != 3
        or sample_array.shape[0] == 0
        or sample_array.shape[1] == 0
        or sample_array.shape[2] != 4
    ):
        raise ValueError("Each calibration sample must contain the same non-zero number of valid ROIs.")
    median_rois = np.median(sample_array, axis=0)
    return tuple(tuple(float(value) for value in roi) for roi in median_rois)


class SmartRenamer(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("SMART RENAMER")
        self.geometry("650x550")
        self.resizable(False, False)
        self.configure(fg_color=APP_BACKGROUND)
        self.roi_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".smart_renamer_rois.json")
        self.field_rois, self.admin_password, self.has_saved_roi_config, config_warning = self.load_configuration()

        self.label = ctk.CTkLabel(
            self,
            text="SMART RENAMER",
            font=("Helvetica Neue", 28, "bold"),
            text_color=TEXT_PRIMARY,
        )
        self.label.pack(pady=(12, 3))
        self.subtitle = ctk.CTkLabel(
            self,
            text="Template ROI Auto Renamer (Images & PDFs)",
            font=("Helvetica Neue", 13),
            text_color=TEXT_SECONDARY,
        )
        self.subtitle.pack(pady=(0, 7))

        self.create_input_field(
            "Select Folder",
            self.select_folder,
            "lbl_folder",
            "No source selected",
            secondary_button=("Select File", self.select_file),
        )
        self.create_input_field(
            "Output Folder",
            self.select_output_folder,
            "lbl_output",
            "Same as source (no overwrite)",
            btn_color=SECONDARY_BUTTON,
        )

        self.btn_calibrate = ctk.CTkButton(
            self,
            text="Teach Number Areas",
            command=self.calibrate_field_rois,
            width=220,
            fg_color=SECONDARY_BUTTON,
            hover_color=SECONDARY_HOVER,
            corner_radius=7,
        )
        self.btn_calibrate.pack(pady=(4, 0))
        self.lbl_calibration = ctk.CTkLabel(
            self,
            text="Saved number areas loaded" if self.has_saved_roi_config else "Default number areas",
            font=("Helvetica Neue", 11),
            text_color=TEXT_SECONDARY,
        )
        self.lbl_calibration.pack(pady=(1, 0))

        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_frame.pack(pady=(8, 0))

        self.progress = ctk.CTkProgressBar(
            self.progress_frame,
            width=400,
            height=12,
            corner_radius=6,
            progress_color=PRIMARY_BUTTON,
            fg_color=SECONDARY_BUTTON,
        )
        self.progress.set(0)
        self.progress.pack()

        self.lbl_status = ctk.CTkLabel(
            self,
            text="Ready",
            font=("Helvetica Neue", 12),
            text_color="#CBD5E1",
        )
        self.lbl_status.pack(pady=(4, 0))

        self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.action_frame.pack(pady=(8, 8))
        self.btn_start = ctk.CTkButton(
            self.action_frame,
            text="START PROCESS",
            command=self.run_process,
            height=40,
            width=190,
            font=("Helvetica Neue", 14, "bold"),
            fg_color=PRIMARY_BUTTON,
            border_width=1,
            border_color=PRIMARY_BUTTON,
            hover_color=PRIMARY_HOVER,
            corner_radius=8,
        )
        self.btn_start.pack(side="left", padx=(0, 8))
        self.btn_cancel = ctk.CTkButton(
            self.action_frame,
            text="CANCEL",
            command=self.cancel_process,
            height=40,
            width=150,
            font=("Helvetica Neue", 14, "bold"),
            fg_color=SECONDARY_BUTTON,
            border_width=1,
            border_color=SECONDARY_BUTTON,
            hover_color=SECONDARY_HOVER,
            corner_radius=8,
        )
        self.btn_cancel.pack(side="left", padx=(8, 0))

        self.signature_frame = ctk.CTkFrame(self, fg_color=FOOTER_BACKGROUND, height=36, corner_radius=0)
        self.signature_frame.pack(side="bottom", fill="x")
        self.brand_canvas = tk.Canvas(
            self.signature_frame,
            width=120,
            height=28,
            background=FOOTER_BACKGROUND,
            highlightthickness=0,
        )
        self.brand_canvas.place(relx=0.5, rely=0.5, anchor="center")
        self.draw_branding()
        self.signature = ctk.CTkLabel(
            self.signature_frame,
            text="Created by Mr. Tamer Ismail",
            font=("Helvetica Neue", 10),
            text_color="#64748B",
        )
        self.signature.place(relx=0.99, rely=0.5, anchor="e")

        self.folder_path = ""
        self.selected_file = ""
        self.output_path = ""
        self.reader = None
        self.worker_events = queue.Queue()
        self.preview_window = None
        self.preview_items = []
        self.cancel_requested = threading.Event()
        self.worker_active = False
        self.after(50, self.process_worker_events)
        if config_warning:
            self.after(100, lambda: messagebox.showwarning("Configuration", config_warning, parent=self))
        try:
            self.save_configuration()
        except OSError as ex:
            self.after(
                100,
                lambda error=ex: messagebox.showerror(
                    "Configuration", f"Could not save the local configuration: {error}", parent=self
                ),
            )

    def draw_branding(self):
        canvas = self.brand_canvas
        scale = 0.34
        offset_x = (120 - 266 * scale) / 2
        offset_y = (28 - 50 * scale) / 2

        def rounded_rectangle(x1, y1, x2, y2, radius, color):
            points = []
            for center_x, center_y, start_angle in (
                (x2 - radius, y1 + radius, -90),
                (x2 - radius, y2 - radius, 0),
                (x1 + radius, y2 - radius, 90),
                (x1 + radius, y1 + radius, 180),
            ):
                for step in range(9):
                    angle = math.radians(start_angle + step * 90 / 8)
                    points.extend((
                        offset_x + (center_x + radius * math.cos(angle)) * scale,
                        offset_y + (center_y + radius * math.sin(angle)) * scale,
                    ))
            return canvas.create_polygon(points, fill=color, outline="", smooth=True, splinesteps=12)

        def line(*coordinates, **options):
            scaled_coordinates = [
                offset_x + coordinate * scale if index % 2 == 0
                else offset_y + coordinate * scale
                for index, coordinate in enumerate(coordinates)
            ]
            options["width"] *= scale
            return canvas.create_line(*scaled_coordinates, **options)

        rounded_rectangle(0, 0, 58, 14, 7, LOGO_WHITE)
        line(29, 7, 29, 43, fill=LOGO_WHITE, width=14, capstyle=tk.ROUND)

        line(78, 7, 128, 7, fill=LOGO_WHITE, width=14, capstyle=tk.ROUND)
        line(78, 25, 121, 25, fill=LOGO_BLUE, width=14, capstyle=tk.ROUND)
        line(78, 43, 128, 43, fill=LOGO_WHITE, width=14, capstyle=tk.ROUND)

        line(
            148, 43, 148, 7, 172, 25, 196, 7, 196, 43,
            fill=LOGO_WHITE,
            width=14,
            capstyle=tk.ROUND,
            joinstyle=tk.ROUND,
        )

        rounded_rectangle(216, 0, 266, 50, 17, LOGO_WHITE)
        rounded_rectangle(230, 13, 252, 37, 11, FOOTER_BACKGROUND)
        dot_x1 = offset_x + 244 * scale
        dot_y1 = offset_y + 13 * scale
        canvas.create_oval(
            dot_x1,
            dot_y1,
            dot_x1 + 8 * scale,
            dot_y1 + 8 * scale,
            fill=LOGO_BLUE,
            outline="",
        )

    def create_input_field(
        self,
        btn_text,
        command,
        label_attr,
        default_text,
        btn_color=SECONDARY_BUTTON,
        secondary_button=None,
    ):
        frame = ctk.CTkFrame(
            self,
            corner_radius=12,
            fg_color=CARD_BACKGROUND,
            border_width=1,
            border_color=SECONDARY_BUTTON,
        )
        frame.pack(pady=4, padx=50, fill="x")

        btn = ctk.CTkButton(
            frame,
            text=btn_text,
            command=command,
            width=140,
            fg_color=btn_color,
            hover_color=SECONDARY_HOVER,
            corner_radius=7,
        )
        btn.pack(side="left", padx=15, pady=6)
        if secondary_button:
            secondary = ctk.CTkButton(
                frame,
                text=secondary_button[0],
                command=secondary_button[1],
                width=105,
                fg_color=SECONDARY_BUTTON,
                hover_color=SECONDARY_HOVER,
                corner_radius=7,
            )
            secondary.pack(side="left", padx=(0, 8), pady=6)

        lbl = ctk.CTkLabel(frame, text=default_text, font=("Helvetica Neue", 12), text_color=TEXT_SECONDARY)
        lbl.pack(side="left", padx=10, fill="x", expand=True)
        setattr(self, label_attr, lbl)

    def select_folder(self):
        selected_folder = filedialog.askdirectory()
        if selected_folder:
            self.selected_file = ""
            self.folder_path = selected_folder
            self.lbl_folder.configure(text=f"Folder: {os.path.basename(self.folder_path)}", text_color=LOGO_BLUE)

    def select_file(self):
        selected_file = filedialog.askopenfilename(
            filetypes=[("Images and PDFs", "*.jpg *.jpeg *.png *.pdf"), ("All files", "*.*")]
        )
        if selected_file:
            self.selected_file = selected_file
            self.folder_path = ""
            self.lbl_folder.configure(text=f"File: {os.path.basename(selected_file)}", text_color=LOGO_BLUE)

    def select_output_folder(self):
        self.output_path = filedialog.askdirectory()
        if self.output_path:
            self.lbl_output.configure(text=f"Dst: {os.path.basename(self.output_path)}", text_color=LOGO_BLUE)

    def load_configuration(self):
        try:
            with open(self.roi_config_path, encoding="utf-8") as config_file:
                config = json.load(config_file)
            if not isinstance(config, dict):
                raise ValueError("Configuration must be a JSON object")
            rois = tuple(tuple(float(value) for value in roi) for roi in config.get("field_rois", ()))
            if not rois or any(
                len(roi) != 4
                or not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1)
                for roi in rois
            ):
                raise ValueError("Invalid ROI profile")
            admin_password = config.get("admin_password", DEFAULT_ADMIN_PASSWORD)
            if not isinstance(admin_password, str) or not admin_password:
                raise ValueError("Invalid admin password in configuration")
            return rois, admin_password, True, ""
        except FileNotFoundError:
            return DEFAULT_FIELD_ROIS, DEFAULT_ADMIN_PASSWORD, False, ""
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as ex:
            warning = f"The saved configuration could not be loaded. Defaults are being used. Details: {ex}"
            return DEFAULT_FIELD_ROIS, DEFAULT_ADMIN_PASSWORD, False, warning

    def save_configuration(self):
        temporary_path = f"{self.roi_config_path}.tmp"
        try:
            with open(temporary_path, "w", encoding="utf-8") as config_file:
                json.dump(
                    {
                        "field_rois": self.field_rois,
                        "admin_password": self.admin_password,
                    },
                    config_file,
                    indent=2,
                )
            os.replace(temporary_path, self.roi_config_path)
        except OSError:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)
            raise

    def load_calibration_image(self, path):
        if os.path.splitext(path)[1].lower() == ".pdf":
            with fitz.open(path) as doc:
                if len(doc) == 0:
                    raise ValueError(f"The PDF has no pages: {os.path.basename(path)}")
                pix = doc[0].get_pixmap(dpi=150, alpha=False)
                image = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                return cv2.cvtColor(image, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)

        encoded = np.fromfile(path, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Could not read image: {os.path.basename(path)}")
        return image

    def select_roi_on_canvas(self, image, sample_index, sample_count, field_index):
        image_height, image_width = image.shape[:2]
        max_width = max(320, min(1200, self.winfo_screenwidth() - 80))
        max_height = max(240, min(700, self.winfo_screenheight() - 220))
        scale = min(1.0, max_width / image_width, max_height / image_height)
        display_width = max(1, round(image_width * scale))
        display_height = max(1, round(image_height * scale))
        preview = cv2.resize(
            image,
            (display_width, display_height),
            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
        )
        preview = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)

        window = ctk.CTkToplevel(self)
        title = f"Sample {sample_index}/{sample_count} | Area {field_index}"
        window.title(title)
        window.configure(fg_color=APP_BACKGROUND)
        window.geometry(f"{display_width + 40}x{display_height + 145}")
        window.transient(self)
        window.grab_set()

        ctk.CTkLabel(
            window,
            text=title,
            font=("Arial", 16, "bold"),
        ).pack(pady=(10, 3))
        ctk.CTkLabel(
            window,
            text="Drag a rectangle around the number, then confirm it.",
            text_color=TEXT_SECONDARY,
        ).pack(pady=(0, 6))

        canvas = tk.Canvas(
            window,
            width=display_width,
            height=display_height,
            highlightthickness=0,
            cursor="crosshair",
        )
        canvas.pack(padx=12, pady=4)
        photo = ImageTk.PhotoImage(Image.fromarray(preview))
        canvas.image = photo
        canvas.create_image(0, 0, image=photo, anchor="nw")
        actions = ctk.CTkFrame(window, fg_color="transparent")
        actions.pack(pady=(4, 10))

        state = {"start": None, "rect": None, "box": None, "result": None}
        confirm_button = ctk.CTkButton(actions, text="Confirm area", state="disabled", width=130)
        confirm_button.configure(
            fg_color=PRIMARY_BUTTON,
            hover_color=PRIMARY_HOVER,
            corner_radius=7,
        )

        def clamp_point(event):
            return (
                min(max(event.x, 0), display_width),
                min(max(event.y, 0), display_height),
            )

        def start_selection(event):
            state["start"] = clamp_point(event)
            state["box"] = None
            confirm_button.configure(state="disabled")
            if state["rect"] is not None:
                canvas.delete(state["rect"])
            state["rect"] = canvas.create_rectangle(
                *state["start"],
                *state["start"],
                outline="#e74c3c",
                width=3,
            )

        def update_selection(event):
            if state["start"] is None:
                return
            end_x, end_y = clamp_point(event)
            start_x, start_y = state["start"]
            canvas.coords(state["rect"], start_x, start_y, end_x, end_y)

        def finish_selection(event):
            if state["start"] is None:
                return
            end_x, end_y = clamp_point(event)
            start_x, start_y = state["start"]
            box = (
                min(start_x, end_x),
                min(start_y, end_y),
                max(start_x, end_x),
                max(start_y, end_y),
            )
            if box[2] - box[0] >= 4 and box[3] - box[1] >= 4:
                state["box"] = box
                confirm_button.configure(state="normal")

        def undo_selection():
            state["box"] = None
            state["start"] = None
            confirm_button.configure(state="disabled")
            if state["rect"] is not None:
                canvas.delete(state["rect"])
                state["rect"] = None

        def confirm_selection():
            if state["box"] is None:
                return
            x1, y1, x2, y2 = state["box"]
            state["result"] = (
                x1 / display_width,
                y1 / display_height,
                x2 / display_width,
                y2 / display_height,
            )
            window.destroy()

        def cancel_selection():
            window.destroy()

        canvas.bind("<ButtonPress-1>", start_selection)
        canvas.bind("<B1-Motion>", update_selection)
        canvas.bind("<ButtonRelease-1>", finish_selection)
        ctk.CTkButton(
            actions,
            text="Undo",
            command=undo_selection,
            width=90,
            fg_color=SECONDARY_BUTTON,
            hover_color=SECONDARY_HOVER,
            corner_radius=7,
        ).pack(
            side="left", padx=4
        )
        confirm_button.configure(command=confirm_selection)
        confirm_button.pack(side="left", padx=4)
        ctk.CTkButton(
            actions,
            text="Cancel calibration",
            command=cancel_selection,
            width=150,
            fg_color=SECONDARY_BUTTON,
            hover_color=SECONDARY_HOVER,
            corner_radius=7,
        ).pack(side="left", padx=4)
        window.protocol("WM_DELETE_WINDOW", cancel_selection)
        window.wait_window()
        return state["result"]

    def calibrate_field_rois(self):
        entered_password = simpledialog.askstring(
            "Admin authentication",
            "Enter the admin password:",
            show="*",
            parent=self,
        )
        if entered_password is None:
            return
        if not hmac.compare_digest(entered_password.encode("utf-8"), self.admin_password.encode("utf-8")):
            messagebox.showerror("Access denied", "The admin password is incorrect.", parent=self)
            return

        sample_paths = filedialog.askopenfilenames(
            parent=self,
            title="Select sample images or PDFs",
            filetypes=[("Images and PDFs", "*.jpg *.jpeg *.png *.pdf"), ("All files", "*.*")],
        )
        if not sample_paths:
            return
        messagebox.showinfo(
            "Teach Number Areas",
            "For each sample, select each extraction area in order. After confirming an area, choose whether "
            "to add another one.\nDrag a box around each number and click Confirm area. You can undo a "
            "selection or cancel the run.",
            parent=self,
        )

        samples = []
        cancelled = False
        expected_roi_count = None
        try:
            for sample_index, path in enumerate(sample_paths, start=1):
                image = self.load_calibration_image(path)
                sample_rois = []

                field_index = 1
                while True:
                    roi = self.select_roi_on_canvas(
                        image,
                        sample_index,
                        len(sample_paths),
                        field_index,
                    )
                    if roi is None:
                        cancelled = True
                        break
                    sample_rois.append(roi)
                    add_another = messagebox.askyesno(
                        "Add extraction region",
                        "Do you want to add another extraction region?",
                        parent=self,
                    )
                    if not add_another:
                        break
                    field_index += 1

                if cancelled:
                    break
                if expected_roi_count is None:
                    expected_roi_count = len(sample_rois)
                elif len(sample_rois) != expected_roi_count:
                    messagebox.showerror(
                        "Calibration failed",
                        "Every sample must use the same number of extraction regions.",
                        parent=self,
                    )
                    return
                samples.append(sample_rois)
        except Exception as ex:
            messagebox.showerror("Calibration failed", str(ex))
            return

        if cancelled:
            messagebox.showinfo("Calibration cancelled", "No ROI settings were changed.")
            return

        trained_rois = aggregate_roi_samples(samples)
        previous_rois = self.field_rois
        self.field_rois = trained_rois
        try:
            self.save_configuration()
        except OSError as ex:
            self.field_rois = previous_rois
            messagebox.showerror("Calibration failed", f"Could not save the ROI profile: {ex}")
            return

        self.has_saved_roi_config = True
        self.lbl_calibration.configure(text=f"Calibrated from {len(samples)} samples", text_color="#2ecc71")
        messagebox.showinfo(
            "Calibration saved",
            f"Saved locations for {len(self.field_rois)} extraction regions from {len(samples)} samples.\n"
            "The saved profile will be used automatically next time.",
            parent=self,
        )

    def run_process(self):
        if self.worker_active:
            return
        if not self.folder_path and not self.selected_file:
            messagebox.showwarning("Alert", "Please select a source folder or file first.")
            return
        if self.selected_file and not os.path.isfile(self.selected_file):
            messagebox.showerror("Error", "The selected source file is not available.")
            return
        if not self.selected_file and not os.path.isdir(self.folder_path):
            messagebox.showerror("Error", "The selected source folder is not available.")
            return
        if self.output_path and not os.path.isdir(self.output_path):
            messagebox.showerror("Error", "The selected output folder is not available.")
            return

        self.cancel_requested.clear()
        self.worker_active = True
        self.btn_start.configure(state="disabled", text="Scanning...")
        self.btn_cancel.configure(state="normal")
        self.progress.set(0)
        self.lbl_status.configure(text="Preparing scan...")
        threading.Thread(target=self.scan_files, daemon=True).start()

    def cancel_process(self):
        if self.preview_window is not None:
            self.cancel_preview()
        elif self.worker_active:
            self.cancel_requested.set()
            self.btn_cancel.configure(state="disabled")
            self.lbl_status.configure(text="Cancellation requested...")

    def init_ocr(self):
        if self.reader is None:
            self.worker_events.put(("status", "Loading locally installed OCR models..."))
            import torch

            torch.set_num_threads(min(4, os.cpu_count() or 1))
            self.reader = easyocr.Reader(["ar", "en"], gpu=False, download_enabled=False)

    def iter_pdf_pages(self, pdf_path):
        with fitz.open(pdf_path) as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=150, alpha=False)
                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                image = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)
                yield page, image

    def read_page_numbers(self, image):
        self.init_ocr()
        image_height, image_width = image.shape[:2]
        numbers = []

        for left, top, right, bottom in self.field_rois:
            x1 = round(image_width * left)
            y1 = round(image_height * top)
            x2 = round(image_width * right)
            y2 = round(image_height * bottom)
            roi = image[y1:y2, x1:x2]
            if roi.size == 0:
                numbers.append("UNKNOWN")
                continue

            roi_height, roi_width = roi.shape[:2]
            scale = min(1.5, 640 / max(roi_height, roi_width))
            roi = cv2.resize(
                roi,
                (max(1, round(roi_width * scale)), max(1, round(roi_height * scale))),
                interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA,
            )
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            denoised = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
            enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(denoised)
            min_dimension = min(enhanced.shape[:2])
            block_size = min(31, min_dimension if min_dimension % 2 else min_dimension - 1)
            if block_size >= 3:
                ocr_image = cv2.adaptiveThreshold(
                    enhanced,
                    255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY,
                    block_size,
                    7,
                )
            else:
                _, ocr_image = cv2.threshold(
                    enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
                )
            detections = self.reader.readtext(
                ocr_image,
                detail=1,
                paragraph=False,
                min_size=5,
                canvas_size=640,
                batch_size=1,
                workers=0,
                allowlist="0123456789",
                mag_ratio=1.5,
                contrast_ths=0.05,
                adjust_contrast=0.7,
                text_threshold=0.5,
                low_text=0.3,
            )

            candidates = []
            for _, text, confidence in detections:
                normalized = text.translate(DIGIT_TRANSLATION)
                for digit_run in re.findall(r"\d+", normalized):
                    candidates.append((digit_run, confidence))

            if candidates:
                number, _ = max(
                    candidates,
                    key=lambda candidate: (
                        len(candidate[0]) == DOCUMENT_NUMBER_LENGTH,
                        -abs(len(candidate[0]) - DOCUMENT_NUMBER_LENGTH),
                        candidate[1],
                    ),
                )
                numbers.append(number)
            else:
                numbers.append("UNKNOWN")

        return tuple(numbers)

    def get_number_length_note_path(self, source_path, note_folder):
        filename = os.path.basename(source_path)
        return os.path.join(note_folder, f"{filename}_ocr_note.txt")

    def write_number_length_note(self, source_path, note_folder, numbers):
        note_path = self.get_number_length_note_path(source_path, note_folder)
        invalid_numbers = [
            (index, number)
            for index, number in enumerate(numbers, start=1)
            if number.isdigit() and len(number) != DOCUMENT_NUMBER_LENGTH
        ]
        if not invalid_numbers:
            return ""

        filename = os.path.basename(source_path)
        lines = [
            f"الملف: {filename}",
            "الأرقام المستخرجة:",
        ]
        lines.extend(
            f"- Area {index}: {number if number != 'UNKNOWN' else 'غير موجود'}"
            for index, number in enumerate(numbers, start=1)
        )
        lines.append("ملاحظات الأرقام التي لا تحتوي على 8 خانات:")
        lines.extend(
            f"- Area {index}: تم استخراج {len(number)} خانات ({number}) بدلًا من 8."
            for index, number in invalid_numbers
        )
        with open(note_path, "w", encoding="utf-8") as note_file:
            note_file.write("\n".join(lines) + "\n")
        return note_path

    def get_target_numbers(self, image_np):
        if image_np is None or image_np.size == 0:
            raise ValueError("The image could not be read.")
        return self.read_page_numbers(image_np)

    def process_worker_events(self):
        while True:
            try:
                event, payload = self.worker_events.get_nowait()
            except queue.Empty:
                break

            if event == "scan_progress":
                index, total, filename = payload
                self.progress.set((index - 1) / total)
                self.lbl_status.configure(text=f"Scanning ({index}/{total}): {filename}")
            elif event == "scan_done":
                self.worker_active = False
                self.btn_cancel.configure(state="normal")
                self.show_preview(payload)
            elif event == "scan_cancelled":
                self.worker_active = False
                self.btn_start.configure(state="normal", text="START PROCESS")
                self.btn_cancel.configure(state="normal")
                self.progress.set(0)
                self.lbl_status.configure(text="Cancelled.")
            elif event == "scan_error":
                self.worker_active = False
                self.finish_with_error("Scan failed", payload)
            elif event == "status":
                self.lbl_status.configure(text=payload)
            elif event == "apply_progress":
                index, total, filename = payload
                self.progress.set(index / total)
                self.lbl_status.configure(text=f"Renaming ({index}/{total}): {filename}")
            elif event == "apply_done":
                renamed, selected_count, errors = payload
                self.worker_active = False
                self.finish_apply(renamed, selected_count, errors)

        self.after(50, self.process_worker_events)

    def scan_files(self):
        try:
            source_folder = os.path.dirname(self.selected_file) if self.selected_file else self.folder_path
            dest_folder = self.output_path or source_folder
            supported_exts = (".jpg", ".jpeg", ".png", ".pdf")
            if self.selected_file:
                files = [os.path.basename(self.selected_file)]
            else:
                files = sorted(f for f in os.listdir(source_folder) if f.lower().endswith(supported_exts))
            if not files:
                self.worker_events.put(("scan_done", []))
                return

            results = []
            reserved_paths = set()
            total = len(files)
            for index, filename in enumerate(files, start=1):
                if self.cancel_requested.is_set():
                    self.worker_events.put(("scan_cancelled", None))
                    return
                self.worker_events.put(("scan_progress", (index, total, filename)))
                source_path = os.path.join(source_folder, filename)
                ext = os.path.splitext(filename)[1]

                try:
                    note_path = self.get_number_length_note_path(source_path, dest_folder)
                    if os.path.exists(note_path):
                        os.remove(note_path)

                    if ext.lower() == ".pdf":
                        numbers = tuple("UNKNOWN" for _ in self.field_rois)
                        best_numbers = numbers
                        for _, image in self.iter_pdf_pages(source_path):
                            if self.cancel_requested.is_set():
                                self.worker_events.put(("scan_cancelled", None))
                                return
                            numbers = self.get_target_numbers(image)
                            if numbers.count("UNKNOWN") < best_numbers.count("UNKNOWN"):
                                best_numbers = numbers
                            if "UNKNOWN" not in numbers:
                                break
                        else:
                            numbers = best_numbers
                    else:
                        numbers = self.get_target_numbers(cv2.imread(source_path))

                    note_error = ""
                    try:
                        self.write_number_length_note(source_path, dest_folder, numbers)
                    except OSError as ex:
                        note_error = f"Note could not be written: {ex}"

                    if "UNKNOWN" in numbers:
                        missing = [
                            label
                            for label, value in zip(("Izn", "Supply", "Invoice"), numbers)
                            if value == "UNKNOWN"
                        ]
                        results.append({
                            "filename": filename,
                            "new_name": "-",
                            "status": f"Not found: {', '.join(missing)}"
                            + (f"; {note_error}" if note_error else ""),
                            "eligible": False,
                        })
                        continue

                    proposed_name = f"{'-'.join(numbers)}{ext}"
                    destination_path, already_named = self.reserve_destination(
                        dest_folder, proposed_name, source_path, reserved_paths
                    )
                    results.append({
                        "filename": filename,
                        "source_path": source_path,
                        "destination_path": destination_path,
                        "new_name": os.path.basename(destination_path),
                        "status": (
                            "Already named" if already_named else "Ready"
                        ) + (f"; {note_error}" if note_error else ""),
                        "eligible": not already_named,
                    })
                except Exception as ex:
                    results.append({
                        "filename": filename,
                        "new_name": "-",
                        "status": f"Error: {ex}",
                        "eligible": False,
                    })

            if self.cancel_requested.is_set():
                self.worker_events.put(("scan_cancelled", None))
            else:
                self.worker_events.put(("scan_done", results))
        except Exception as ex:
            self.worker_events.put(("scan_error", str(ex)))

    def reserve_destination(self, dest_folder, proposed_name, source_path, reserved_paths):
        source_key = os.path.normcase(os.path.abspath(source_path))
        candidate = os.path.join(dest_folder, proposed_name)
        candidate_key = os.path.normcase(os.path.abspath(candidate))
        if candidate_key == source_key:
            return candidate, True

        stem, ext = os.path.splitext(proposed_name)
        suffix = 2
        while os.path.exists(candidate) or candidate_key in reserved_paths:
            candidate = os.path.join(dest_folder, f"{stem}_{suffix}{ext}")
            candidate_key = os.path.normcase(os.path.abspath(candidate))
            suffix += 1

        reserved_paths.add(candidate_key)
        return candidate, False

    def show_preview(self, results):
        if not results:
            self.finish_with_error("Info", "No supported images or PDFs were found in the source folder.")
            return

        self.preview_items = results
        ready_count = sum(item["eligible"] for item in results)
        skipped_count = len(results) - ready_count
        self.lbl_status.configure(text=f"Review results: {ready_count} ready, {skipped_count} skipped")

        window = ctk.CTkToplevel(self)
        self.preview_window = window
        window.title("Review Rename Results")
        window.geometry("900x560")
        window.configure(fg_color=APP_BACKGROUND)
        window.transient(self)
        window.grab_set()
        window.protocol("WM_DELETE_WINDOW", self.cancel_preview)

        ctk.CTkLabel(
            window,
            text="Review before renaming",
            font=("Helvetica Neue", 20, "bold"),
            text_color=TEXT_PRIMARY,
        ).pack(pady=(18, 4))
        ctk.CTkLabel(
            window,
            text=f"{ready_count} files ready to rename; {skipped_count} skipped or already named.",
            text_color=TEXT_SECONDARY,
        ).pack(pady=(0, 12))

        headers = ctk.CTkFrame(window, fg_color="transparent")
        headers.pack(fill="x", padx=18)
        for text, width in (("Rename", 65), ("Current file", 260), ("Proposed name", 300), ("Result", 210)):
            ctk.CTkLabel(
                headers,
                text=text,
                width=width,
                anchor="w",
                font=("Helvetica Neue", 12, "bold"),
                text_color=TEXT_PRIMARY,
            ).pack(
                side="left", padx=4
            )

        rows = ctk.CTkScrollableFrame(
            window,
            height=360,
            fg_color=CARD_BACKGROUND,
            corner_radius=12,
        )
        rows.pack(fill="both", expand=True, padx=18, pady=(4, 12))
        for item in results:
            row = ctk.CTkFrame(rows, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=3)
            if item["eligible"]:
                item["selected"] = ctk.BooleanVar(value=True)
                ctk.CTkCheckBox(row, text="", variable=item["selected"], width=55).pack(side="left", padx=4)
            else:
                ctk.CTkLabel(row, text="-", width=55, anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(row, text=item["filename"], width=260, anchor="w", wraplength=245).pack(side="left", padx=4)
            ctk.CTkLabel(row, text=item["new_name"], width=300, anchor="w", wraplength=285).pack(side="left", padx=4)
            ctk.CTkLabel(row, text=item["status"], width=210, anchor="w", wraplength=195).pack(side="left", padx=4)

        actions = ctk.CTkFrame(window, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(0, 14))
        ctk.CTkButton(
            actions,
            text="Cancel",
            command=self.cancel_preview,
            fg_color=SECONDARY_BUTTON,
            hover_color=SECONDARY_HOVER,
            corner_radius=7,
        ).pack(
            side="right", padx=(8, 0)
        )
        rename_button = ctk.CTkButton(
            actions,
            text="Rename selected",
            command=self.apply_selected,
            fg_color=PRIMARY_BUTTON,
            hover_color=PRIMARY_HOVER,
            corner_radius=8,
        )
        rename_button.pack(side="right")
        if ready_count == 0:
            rename_button.configure(state="disabled")

    def cancel_preview(self):
        if self.preview_window is not None:
            self.preview_window.grab_release()
            self.preview_window.destroy()
            self.preview_window = None
        self.finish_with_error("", "Review cancelled.", show_dialog=False)

    def apply_selected(self):
        selected = [item for item in self.preview_items if item.get("selected") and item["selected"].get()]
        if not selected:
            messagebox.showwarning("No files selected", "Select at least one file to rename.")
            return

        self.preview_window.grab_release()
        self.preview_window.destroy()
        self.preview_window = None
        self.worker_active = True
        self.btn_cancel.configure(state="normal")
        self.lbl_status.configure(text="Applying selected names...")
        threading.Thread(target=self.apply_renames, args=(selected,), daemon=True).start()

    def apply_renames(self, selected):
        renamed = 0
        errors = []
        total = len(selected)

        for index, item in enumerate(selected, start=1):
            if self.cancel_requested.is_set():
                break
            source_path = item["source_path"]
            destination_path = item["destination_path"]
            try:
                if os.path.exists(destination_path):
                    raise FileExistsError(f"Target already exists: {os.path.basename(destination_path)}")

                if self.output_path:
                    created_destination = False
                    try:
                        with open(source_path, "rb") as source, open(destination_path, "xb") as destination:
                            created_destination = True
                            shutil.copyfileobj(source, destination)
                        shutil.copystat(source_path, destination_path)
                    except Exception:
                        if created_destination and os.path.exists(destination_path):
                            os.unlink(destination_path)
                        raise
                else:
                    os.link(source_path, destination_path)
                    try:
                        os.unlink(source_path)
                    except OSError:
                        os.unlink(destination_path)
                        raise
                renamed += 1
            except Exception as ex:
                errors.append(f"{item['filename']}: {ex}")

            self.worker_events.put(("apply_progress", (index, total, item["filename"])))

        self.worker_events.put(("apply_done", (renamed, total, errors, self.cancel_requested.is_set())))

    def finish_apply(self, renamed, selected_count, errors, cancelled=False):
        not_selected = sum(item["eligible"] for item in self.preview_items) - selected_count
        self.btn_start.configure(state="normal", text="START PROCESS")
        self.btn_cancel.configure(state="normal")
        self.progress.set(0)
        self.lbl_status.configure(text="Cancelled." if cancelled else f"Completed: {renamed} renamed")

        details = f"Renamed {renamed} of {selected_count} selected files."
        if cancelled:
            details += "\nCancellation requested; no further files were processed."
        if not_selected:
            details += f"\nLeft unchanged: {not_selected} deselected file(s)."
        if errors:
            details += f"\nFailed: {len(errors)}"
            details += "\n" + "\n".join(errors[:5])
            if len(errors) > 5:
                details += f"\nAnd {len(errors) - 5} more."
        messagebox.showinfo("Rename complete", details)
        self.preview_items = []

    def finish_with_error(self, title, message, show_dialog=True):
        self.worker_active = False
        self.btn_start.configure(state="normal", text="START PROCESS")
        self.btn_cancel.configure(state="normal")
        self.progress.set(0)
        self.lbl_status.configure(text=message if title else "Ready")
        if show_dialog:
            if title == "Info":
                messagebox.showinfo(title, message)
            else:
                messagebox.showerror(title, message)
        self.preview_items = []


if __name__ == "__main__":
    app = SmartRenamer()
    app.mainloop()