import os
import re
import cv2
import queue
import shutil
import threading
import numpy as np
import pymupdf as fitz
import customtkinter as ctk
from tkinter import filedialog, messagebox

try:
    from pyzbar.pyzbar import decode as zbar_decode
    from pyzbar.pyzbar import ZBarSymbol
except (ImportError, OSError):
    zbar_decode = None
    ZBarSymbol = None


def get_roi_by_region(image, region_type):
    if image is None or image.size == 0:
        return image

    height, width = image.shape[:2]
    h_crop = int(height * 0.45)
    w_crop = int(width * 0.45)

    if region_type == "top_left":
        return image[0:h_crop, 0:w_crop]
    elif region_type == "bottom_right":
        return image[max(0, height - h_crop):height, max(0, width - w_crop):width]
    elif region_type == "top_right":
        return image[0:h_crop, max(0, width - w_crop):width]
    elif region_type == "bottom_left":
        return image[max(0, height - h_crop):height, 0:w_crop]
    elif region_type == "full":
        return image
    
    return image


def rotate_image(image, angle):
    """
    تدوير الصورة بأي زاوية مع الحفاظ على الأبعاد كاملة دون اقتطاع الحواف
    """
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cosine = abs(rotation_matrix[0, 0])
    sine = abs(rotation_matrix[0, 1])
    
    new_width = int((height * sine) + (width * cosine))
    new_height = int((height * cosine) + (width * sine))
    
    rotation_matrix[0, 2] += (new_width / 2.0) - center[0]
    rotation_matrix[1, 2] += (new_height / 2.0) - center[1]
    
    return cv2.warpAffine(
        image,
        rotation_matrix,
        (new_width, new_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255) if image.ndim == 3 else 255
    )


def generate_image_variants(gray_img):
    """
    توليد فلترات تحسين التباين والمعالجة
    """
    enlarged = cv2.resize(gray_img, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrast = clahe.apply(enlarged)
    
    _, otsu = cv2.threshold(contrast, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    
    sharpened = cv2.filter2D(
        enlarged,
        ddepth=-1,
        kernel=np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    )
    
    variants = [enlarged, otsu, sharpened]
    
    min_dim = min(sharpened.shape[:2])
    block_size = min(21, min_dim if min_dim % 2 else min_dim - 1)
    if block_size >= 3:
        adaptive = cv2.adaptiveThreshold(
            sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, 5
        )
        variants.append(adaptive)
        
    return variants


# إعدادات الواجهة
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG_MAIN = "#0B0F19"
BG_CARD = "#151C2C"
BORDER_COLOR = "#232D42"
ACCENT_BLUE = "#2563EB"
ACCENT_HOVER = "#1D4ED8"
TEXT_TITLE = "#F8FAFC"
TEXT_MUTED = "#64748B"
CANCEL_BTN = "#1E293B"
UNREADABLE_QR_REPORT = "QR_Not_Readable.txt"
NOT_FOUND_IMAGES_FOLDER = "not_found_images"
NOT_FOUND_IMAGES_REPORT = "not_found_list.txt"


class ModernQRRenamer(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("QR Document Processor")
        self.geometry("700x650")
        self.resizable(False, False)
        self.configure(fg_color=BG_MAIN)

        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(pady=(20, 10), padx=40, fill="x")

        self.lbl_title = ctk.CTkLabel(
            self.header_frame,
            text="QR Document Processor",
            font=("Segoe UI", 28, "bold"),
            text_color=TEXT_TITLE,
            anchor="w"
        )
        self.lbl_title.pack(fill="x")

        self.lbl_subtitle = ctk.CTkLabel(
            self.header_frame,
            text="High-performance batch renamer powered by QR detection",
            font=("Segoe UI", 12),
            text_color=TEXT_MUTED,
            anchor="w"
        )
        self.lbl_subtitle.pack(fill="x")

        self.io_card = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=14, border_width=1, border_color=BORDER_COLOR
        )
        self.io_card.pack(pady=10, padx=40, fill="x")

        self.create_io_row(
            self.io_card,
            "Select Folder", 
            self.select_folder,
            "lbl_folder",
            "No source selected",
            secondary_btn=("Single File", self.select_file)
        )

        ctk.CTkFrame(self.io_card, height=1, fg_color=BORDER_COLOR).pack(fill="x", padx=15, pady=2)

        self.copy_unreadable_var = ctk.BooleanVar(value=True)
        self.create_io_row(
            self.io_card,
            "Output Folder",
            self.select_output_folder,
            "lbl_output",
            "Same as source (No overwrite)",
            trailing_text="Unnamed images",
            trailing_variable=self.copy_unreadable_var,
        )

        self.options_card = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=14, border_width=1, border_color=BORDER_COLOR
        )
        self.options_card.pack(pady=10, padx=40, fill="x")

        self.lbl_opt_title = ctk.CTkLabel(
            self.options_card,
            text="NAMING PATTERN",
            font=("Segoe UI", 11, "bold"),
            text_color=TEXT_MUTED
        )
        self.lbl_opt_title.pack(anchor="w", padx=20, pady=(12, 6))

        self.format_var = ctk.IntVar(value=1)

        self.radio_mode1 = ctk.CTkRadioButton(
            self.options_card,
            text="Ref - RI (Default)",
            variable=self.format_var,
            value=1,
            font=("Segoe UI", 12),
            fg_color=ACCENT_BLUE,
            hover_color=ACCENT_HOVER
        )
        self.radio_mode1.pack(anchor="w", padx=25, pady=4)

        self.radio_mode2 = ctk.CTkRadioButton(
            self.options_card,
            text="Custom Short (Ref - RI - PO)",
            variable=self.format_var,
            value=2,
            font=("Segoe UI", 12),
            fg_color=ACCENT_BLUE,
            hover_color=ACCENT_HOVER
        )
        self.radio_mode2.pack(anchor="w", padx=25, pady=4)

        self.radio_mode3 = ctk.CTkRadioButton(
            self.options_card,
            text="Full Data",
            variable=self.format_var,
            value=3,
            font=("Segoe UI", 12),
            fg_color=ACCENT_BLUE,
            hover_color=ACCENT_HOVER
        )
        self.radio_mode3.pack(anchor="w", padx=25, pady=4)

        self.status_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.status_frame.pack(pady=(10, 0), padx=40, fill="x")

        self.progress = ctk.CTkProgressBar(
            self.status_frame,
            height=10,
            corner_radius=5,
            progress_color=ACCENT_BLUE,
            fg_color=BORDER_COLOR
        )
        self.progress.set(0)
        self.progress.pack(fill="x")

        self.lbl_status = ctk.CTkLabel(
            self.status_frame,
            text="System Ready",
            font=("Segoe UI", 12),
            text_color=TEXT_MUTED
        )
        self.lbl_status.pack(pady=(6, 0))

        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.pack(pady=(15, 10))

        self.btn_start = ctk.CTkButton(
            self.btn_frame,
            text="START PROCESS",
            command=self.run_process,
            height=46,
            width=220,
            font=("Segoe UI", 14, "bold"),
            fg_color=ACCENT_BLUE,
            hover_color=ACCENT_HOVER,
            corner_radius=10
        )
        self.btn_start.pack(side="left", padx=8)

        self.btn_cancel = ctk.CTkButton(
            self.btn_frame,
            text="CANCEL",
            command=self.cancel_process,
            height=46,
            width=130,
            font=("Segoe UI", 13, "bold"),
            fg_color=CANCEL_BTN,
            hover_color="#334155",
            corner_radius=10
        )
        self.btn_cancel.pack(side="left", padx=8)

        self.footer = ctk.CTkFrame(self, fg_color=BG_CARD, height=40, corner_radius=0)
        self.footer.pack(side="bottom", fill="x")

        self.lbl_footer = ctk.CTkLabel(
            self.footer,
            text="Created by Mr. Tamer Ismail",
            font=("Segoe UI", 11),
            text_color=TEXT_MUTED
        )
        self.lbl_footer.pack(side="right", padx=20)

        self.folder_path = ""
        self.selected_file = ""
        self.output_path = ""
        self.result_folder = ""
        self.worker_events = queue.Queue()
        self.preview_window = None
        self.preview_items = []
        self.failed_files = []
        self.unreadable_report_path = ""
        self.not_found_report_path = ""
        self.not_found_folder = ""
        self.cancel_requested = threading.Event()
        self.worker_active = False
        self.qr_detector = cv2.QRCodeDetector()
        self.naming_mode = self.format_var.get()

        self.after(50, self.process_worker_events)

    def create_io_row(
        self, parent, btn_text, command, attr_name, default_txt,
        secondary_btn=None, trailing_text=None, trailing_variable=None
    ):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=8)

        btn = ctk.CTkButton(
            row, text=btn_text, command=command, width=120, height=32,
            fg_color=BORDER_COLOR, hover_color="#334155", corner_radius=8, font=("Segoe UI", 12, "bold")
        )
        btn.pack(side="left", padx=(0, 8))

        if secondary_btn:
            sec_btn = ctk.CTkButton(
                row, text=secondary_btn[0], command=secondary_btn[1], width=100, height=32,
                fg_color=BORDER_COLOR, hover_color="#334155", corner_radius=8, font=("Segoe UI", 12)
            )
            sec_btn.pack(side="left", padx=(0, 10))

        if trailing_text:
            self.copy_unreadable_checkbox = ctk.CTkCheckBox(
                row, text=trailing_text, variable=trailing_variable, font=("Segoe UI", 12),
                checkbox_width=18, checkbox_height=18, border_width=2,
                fg_color=ACCENT_BLUE, hover_color=ACCENT_HOVER
            )
            self.copy_unreadable_checkbox.pack(side="right", padx=(10, 0))

        lbl = ctk.CTkLabel(row, text=default_txt, font=("Segoe UI", 12), text_color=TEXT_MUTED, anchor="w")
        lbl.pack(side="left", fill="x", expand=True)
        setattr(self, attr_name, lbl)

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.selected_file = ""
            self.folder_path = folder
            self.lbl_folder.configure(text=os.path.basename(folder), text_color=TEXT_TITLE)

    def select_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("PDF & Images", "*.pdf *.jpg *.jpeg *.png")])
        if file_path:
            self.folder_path = ""
            self.selected_file = file_path
            self.lbl_folder.configure(text=os.path.basename(file_path), text_color=TEXT_TITLE)

    def select_output_folder(self):
        out_folder = filedialog.askdirectory()
        if out_folder:
            self.output_path = out_folder
            self.lbl_output.configure(text=os.path.basename(out_folder), text_color=TEXT_TITLE)

    def parse_qr_text(self, raw_text):
        keys_order = ['e', 'c', 'pr', 'po', 'ri', 'ref']
        parsed_data = {}

        matches = re.findall(r"['\"]?([a-zA-Z]+)['\"]?\s*:\s*['\"]?(\d+)['\"]?", raw_text)
        if not matches:
            matches = re.findall(r"([a-zA-Z]+)\s*['\"]?(\d+)['\"]?", raw_text)

        for k, v in matches:
            parsed_data[k.lower()] = v

        mode = self.naming_mode
        
        if mode == 1:
            vals = [parsed_data.get(k, '') for k in ('ref', 'ri') if parsed_data.get(k)]
            if vals:
                return " - ".join(vals)
        elif mode == 2:
            vals = [parsed_data.get(k, '') for k in ('ref', 'ri', 'po') if parsed_data.get(k)]
            if vals:
                return " - ".join(vals)
        elif mode == 3:
            vals = [parsed_data.get(k, '') for k in keys_order if parsed_data.get(k)]
            if vals:
                return " - ".join(vals)

        digits = re.findall(r'\d+', raw_text)
        if digits:
            if mode == 1 and len(digits) >= 2:
                return " - ".join(digits[-1:-3:-1])
            if mode == 2 and len(digits) >= 3:
                return " - ".join(digits[-1:-4:-1])
            return " - ".join(digits)
            
        return "UNKNOWN"

    def try_decode(self, roi):
        """
        محاولة قراءة الـ QR من المقتطع عبر الفلترات المختلفة
        """
        if roi is None or roi.size == 0:
            return "UNKNOWN"

        if roi.ndim == 3:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        else:
            gray = roi

        variants = generate_image_variants(gray)

        # 1. PyZBar
        if zbar_decode is not None:
            for var in variants:
                try:
                    decoded_objects = zbar_decode(var, symbols=[ZBarSymbol.QRCODE])
                except Exception:
                    decoded_objects = ()
                for decoded in decoded_objects:
                    raw_text = decoded.data.decode("utf-8", errors="ignore")
                    if raw_text:
                        parsed = self.parse_qr_text(raw_text)
                        if parsed != "UNKNOWN":
                            return parsed

        # 2. OpenCV QRDetector
        for var in variants:
            try:
                data, _, _ = self.qr_detector.detectAndDecode(var)
            except cv2.error:
                continue
            if data:
                parsed = self.parse_qr_text(data)
                if parsed != "UNKNOWN":
                    return parsed

        return "UNKNOWN"

    def decode_qr_from_image(self, image):
        """
        حلقة فحص متكاملة وتكرارية تجرّب:
        1. التدويرات الرئيسية (0, 180, 90, 270)
        2. التدويرات الدقيقة للميلان (-15, -10, -5, 5, 10, 15)
        3. فحص الأركان الأربعة + الصورة الكاملة
        """
        if image is None or not isinstance(image, np.ndarray) or image.size == 0:
            return "UNKNOWN"

        regions = ["top_left", "bottom_right", "top_right", "bottom_left", "full"]
        
        # قائمة الزوايا الشاملة: (الاتجاهات الرئيسية ثم الميلان الدقيق)
        rotation_angles = [0, 180, 90, 270, -5, 5, -10, 10, -15, 15]

        for angle in rotation_angles:
            if self.cancel_requested.is_set():
                return "UNKNOWN"

            # تدوير الصورة بالزاوية المطلوبة
            rotated_img = rotate_image(image, angle) if angle != 0 else image

            # فحص المناطق والكامل
            for reg in regions:
                roi = get_roi_by_region(rotated_img, reg)
                result = self.try_decode(roi)
                if result != "UNKNOWN":
                    return result

        return "UNKNOWN"

    def run_process(self):
        if self.worker_active:
            return
        if not self.folder_path and not self.selected_file:
            messagebox.showwarning("Warning", "Please select a source folder or file first.")
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
        self.naming_mode = self.format_var.get()
        copy_unreadable = self.copy_unreadable_var.get()
        self.worker_active = True
        self.failed_files = []
        self.unreadable_report_path = ""
        self.not_found_report_path = ""
        self.not_found_folder = ""
        self.btn_start.configure(state="disabled", text="Scanning...")
        self.btn_cancel.configure(state="normal")
        self.copy_unreadable_checkbox.configure(state="disabled")
        self.progress.set(0)
        self.lbl_status.configure(text="Scanning QR Codes...")
        threading.Thread(
            target=self.scan_files,
            args=(copy_unreadable,),
            daemon=True,
        ).start()

    def cancel_process(self):
        if self.preview_window:
            self.cancel_preview()
        elif self.worker_active:
            self.cancel_requested.set()
            self.lbl_status.configure(text="Cancelling process...")

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
                self.copy_unreadable_checkbox.configure(state="normal")
                self.show_preview(payload)
            elif event == "scan_cancelled":
                self.worker_active = False
                self.btn_start.configure(state="normal", text="START PROCESS")
                self.copy_unreadable_checkbox.configure(state="normal")
                self.progress.set(0)
                self.lbl_status.configure(text="Cancelled.")
            elif event == "scan_error":
                self.worker_active = False
                self.finish_with_error("Scan failed", payload)
            elif event == "scan_report_error":
                messagebox.showerror(
                    "Report could not be saved",
                    f"Could not save the list of files without readable QR codes:\n{payload}",
                )
            elif event == "apply_progress":
                index, total, filename = payload
                self.progress.set(index / total)
                self.lbl_status.configure(text=f"Renaming ({index}/{total}): {filename}")
            elif event == "apply_done":
                renamed, selected_count, errors, cancelled = payload
                self.worker_active = False
                self.finish_apply(renamed, selected_count, errors, cancelled)

        self.after(50, self.process_worker_events)

    def scan_files(self, copy_unreadable=False):
        try:
            source_folder = os.path.dirname(self.selected_file) if self.selected_file else self.folder_path
            dest_folder = self.output_path or os.path.join(source_folder, "result")
            os.makedirs(dest_folder, exist_ok=True)
            self.result_folder = dest_folder
            supported_exts = (".jpg", ".jpeg", ".png", ".pdf")

            files = (
                [os.path.basename(self.selected_file)]
                if self.selected_file
                else sorted(
                    filename
                    for filename in os.listdir(source_folder)
                    if filename.lower().endswith(supported_exts)
                    and os.path.isfile(os.path.join(source_folder, filename))
                )
            )

            if not files:
                self.worker_events.put(("scan_done", []))
                return

            results = []
            not_found_files = []
            reserved_paths = set()
            total = len(files)

            for index, filename in enumerate(files, start=1):
                if self.cancel_requested.is_set():
                    self.worker_events.put(("scan_cancelled", None))
                    return

                self.worker_events.put(("scan_progress", (index, total, filename)))
                source_path = os.path.join(source_folder, filename)
                ext = os.path.splitext(filename)[1]
                qr_data = "UNKNOWN"

                try:
                    if ext.lower() == ".pdf":
                        with fitz.open(source_path) as doc:
                            for page in doc:
                                if self.cancel_requested.is_set():
                                    self.worker_events.put(("scan_cancelled", None))
                                    return
                                pix = page.get_pixmap(dpi=150, alpha=False)
                                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                                image = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)
                                qr_data = self.decode_qr_from_image(image)
                                if qr_data != "UNKNOWN":
                                    break
                    else:
                        encoded_image = np.fromfile(source_path, dtype=np.uint8)
                        image = cv2.imdecode(encoded_image, cv2.IMREAD_COLOR)
                        if image is None:
                            raise ValueError(f"Could not read image: {os.path.basename(source_path)}")
                        qr_data = self.decode_qr_from_image(image)

                    if qr_data == "UNKNOWN":
                        self.failed_files.append(filename)
                        status = "QR Code Not Found"
                        if copy_unreadable:
                            not_found_files.append(filename)
                            self.not_found_folder = os.path.join(dest_folder, NOT_FOUND_IMAGES_FOLDER)
                            try:
                                os.makedirs(self.not_found_folder, exist_ok=True)
                                shutil.copy2(source_path, os.path.join(self.not_found_folder, filename))
                            except OSError as ex:
                                status += f"; copy failed: {ex}"
                        results.append({"filename": filename, "new_name": "-", "status": status, "eligible": False})
                        continue

                    proposed_name = f"{qr_data}{ext}"
                    destination_path, already_named = self.reserve_destination(
                        dest_folder, proposed_name, source_path, reserved_paths
                    )
                    results.append({
                        "filename": filename,
                        "source_path": source_path,
                        "destination_path": destination_path,
                        "new_name": os.path.basename(destination_path),
                        "status": "Already named" if already_named else "Ready",
                        "eligible": not already_named,
                    })
                except Exception as ex:
                    self.failed_files.append(filename)
                    results.append({"filename": filename, "new_name": "-", "status": f"Error: {ex}", "eligible": False})

            if self.cancel_requested.is_set():
                self.worker_events.put(("scan_cancelled", None))
            else:
                report_path = os.path.join(dest_folder, UNREADABLE_QR_REPORT)
                try:
                    with open(report_path, "w", encoding="utf-8") as report:
                        report.write("\n".join(self.failed_files))
                    self.unreadable_report_path = report_path if self.failed_files else ""
                except OSError as ex:
                    self.worker_events.put(("scan_report_error", str(ex)))
                if copy_unreadable and not_found_files:
                    not_found_report_path = os.path.join(self.not_found_folder, NOT_FOUND_IMAGES_REPORT)
                    try:
                        with open(not_found_report_path, "w", encoding="utf-8") as report:
                            report.write("\n".join(not_found_files))
                        self.not_found_report_path = not_found_report_path
                    except OSError as ex:
                        self.worker_events.put(("scan_report_error", str(ex)))
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
            self.finish_with_error("Info", "No supported images or PDFs were found in the selected source.")
            return

        self.preview_items = results
        ready_count = sum(item["eligible"] for item in results)
        skipped_count = len(results) - ready_count
        self.lbl_status.configure(text=f"Review results: {ready_count} ready, {skipped_count} skipped")

        window = ctk.CTkToplevel(self)
        self.preview_window = window
        window.title("Review Rename Results")
        window.geometry("900x720")
        window.resizable(True, True)
        window.configure(fg_color=BG_MAIN)
        window.transient(self)
        window.grab_set()
        window.protocol("WM_DELETE_WINDOW", self.cancel_preview)

        ctk.CTkLabel(
            window, text="Review before renaming", font=("Segoe UI", 20, "bold"), text_color=TEXT_TITLE
        ).pack(pady=(18, 4))
        ctk.CTkLabel(
            window,
            text=(
                f"{ready_count} files ready to rename; {skipped_count} skipped or already named."
                f"\nResults folder: {self.result_folder}"
                + (f"\nFiles without readable QR codes were listed in:\n{self.unreadable_report_path}" if self.unreadable_report_path else "")
                + (f"\nUnreadable images copied to:\n{self.not_found_folder}\nList: {self.not_found_report_path}" if self.not_found_report_path else "")
            ),
            text_color=TEXT_MUTED,
        ).pack(pady=(0, 12))

        headers = ctk.CTkFrame(window, fg_color="transparent")
        headers.pack(fill="x", padx=18)
        for text, width in (("Rename", 65), ("Current file", 260), ("Proposed name", 300), ("Result", 210)):
            ctk.CTkLabel(
                headers, text=text, width=width, anchor="w", font=("Segoe UI", 12, "bold"), text_color=TEXT_TITLE
            ).pack(side="left", padx=4)

        rows = ctk.CTkScrollableFrame(window, height=360, fg_color=BG_CARD, corner_radius=12)
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
            actions, text="Cancel", command=self.cancel_preview, fg_color=CANCEL_BTN, hover_color="#334155", corner_radius=7
        ).pack(side="right", padx=(8, 0))
        rename_button = ctk.CTkButton(
            actions, text="Rename selected", command=self.apply_selected, fg_color=ACCENT_BLUE, hover_color=ACCENT_HOVER, corner_radius=8
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

        if self.preview_window is not None:
            self.preview_window.grab_release()
            self.preview_window.destroy()
            self.preview_window = None
        self.cancel_requested.clear()
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
            created_destination = False
            try:
                with open(source_path, "rb") as source, open(destination_path, "xb") as destination:
                    created_destination = True
                    shutil.copyfileobj(source, destination)
                shutil.copystat(source_path, destination_path)
                renamed += 1
            except Exception as ex:
                if created_destination and os.path.exists(destination_path):
                    try:
                        os.unlink(destination_path)
                    except OSError as cleanup_error:
                        errors.append(f"{item['filename']}: {ex}; could not remove incomplete target: {cleanup_error}")
                        self.worker_events.put(("apply_progress", (index, total, item["filename"])))
                        continue
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
        self.copy_unreadable_checkbox.configure(state="normal")
        self.progress.set(0)
        self.lbl_status.configure(text=message if title else "Ready")
        if show_dialog:
            if title == "Info":
                messagebox.showinfo(title, message)
            else:
                messagebox.showerror(title, message)
        self.preview_items = []


if __name__ == "__main__":
    app = ModernQRRenamer()
    app.mainloop()
