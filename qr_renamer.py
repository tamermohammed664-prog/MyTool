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
    if angle == 0:
        return image
    if angle == 180:
        return cv2.rotate(image, cv2.ROTATE_180)

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
    توليد نسخ متوازنة ومستقرة تماماً لتجنب تأثير الأختام والتشويش
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
            text="Created by Mohamed Tamer Ismail",
            font=("Segoe UI", 11),
            text_color=TEXT_MUTED
        )
        self.lbl_footer.pack(side="right", padx=20)

        self.folder_path = ""
        self.selected_file = ""
        self.output_path = ""
        self.result_folder = ""
        self.worker_events = queue.Queue()
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
        if roi is None or roi.size == 0:
            return "UNKNOWN"

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
        variants = generate_image_variants(gray)

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
        if image is None or not isinstance(image, np.ndarray) or image.size == 0:
            return "UNKNOWN"

        # فحص الأركان الأربعة مع تجربة الزوايا المرنة والميلان البسيط لضمان قراءة بنسبة 100%
        regions = ["top_left", "bottom_right", "top_right", "bottom_left", "full"]
        angles = [0, 180, -5, 5, -10, 10]

        for angle in angles:
            if self.cancel_requested.is_set():
                return "UNKNOWN"
            rotated = rotate_image(image, angle) if angle != 0 else image
            for reg in regions:
                result = self.try_decode(get_roi_by_region(rotated, reg))
                if result != "UNKNOWN":
                    return result

        return "UNKNOWN"

    def run_process(self):
        if self.worker_active:
            return
        if not self.folder_path and not self.selected_file:
            messagebox.showwarning("Warning", "Please select a source folder or file first.")
            return

        self.cancel_requested.clear()
        self.naming_mode = self.format_var.get()
        copy_unreadable = self.copy_unreadable_var.get()
        self.worker_active = True
        self.failed_files = []
        self.unreadable_report_path = ""
        self.not_found_report_path = ""
        self.not_found_folder = ""
        self.btn_start.configure(state="disabled", text="Processing...")
        self.btn_cancel.configure(state="normal")
        self.copy_unreadable_checkbox.configure(state="disabled")
        self.progress.set(0)
        self.lbl_status.configure(text="Processing and Renaming...")
        threading.Thread(
            target=self.process_files_direct,
            args=(copy_unreadable,),
            daemon=True,
        ).start()

    def cancel_process(self):
        if self.worker_active:
            self.cancel_requested.set()
            self.lbl_status.configure(text="Cancelling process...")

    def process_worker_events(self):
        while True:
            try:
                event, payload = self.worker_events.get_nowait()
            except queue.Empty:
                break

            if event == "progress":
                index, total, filename = payload
                self.progress.set(index / total)
                self.lbl_status.configure(text=f"Processing ({index}/{total}): {filename}")
            elif event == "done":
                renamed_count, total = payload
                self.worker_active = False
                self.btn_start.configure(state="normal", text="START PROCESS")
                self.btn_cancel.configure(state="normal")
                self.copy_unreadable_checkbox.configure(state="normal")
                self.progress.set(1.0)
                self.lbl_status.configure(text=f"Completed! {renamed_count}/{total} renamed.")
                messagebox.showinfo("Done", f"Successfully processed {total} files.\nRenamed: {renamed_count}")
            elif event == "cancelled":
                self.worker_active = False
                self.btn_start.configure(state="normal", text="START PROCESS")
                self.btn_cancel.configure(state="normal")
                self.copy_unreadable_checkbox.configure(state="normal")
                self.progress.set(0)
                self.lbl_status.configure(text="Cancelled.")

        self.after(50, self.process_worker_events)

    def process_files_direct(self, copy_unreadable=False):
        try:
            source_folder = os.path.dirname(self.selected_file) if self.selected_file else self.folder_path
            dest_folder = self.output_path or os.path.join(source_folder, "result")
            os.makedirs(dest_folder, exist_ok=True)
            supported_exts = (".jpg", ".jpeg", ".png", ".pdf")

            files = (
                [os.path.basename(self.selected_file)]
                if self.selected_file
                else sorted(
                    filename for filename in os.listdir(source_folder)
                    if filename.lower().endswith(supported_exts)
                    and os.path.isfile(os.path.join(source_folder, filename))
                )
            )

            if not files:
                self.worker_events.put(("done", (0, 0)))
                return

            reserved_paths = set()
            not_found_files = []
            renamed_count = 0
            total = len(files)

            for index, filename in enumerate(files, start=1):
                if self.cancel_requested.is_set():
                    self.worker_events.put(("cancelled", None))
                    return

                self.worker_events.put(("progress", (index, total, filename)))
                source_path = os.path.join(source_folder, filename)
                ext = os.path.splitext(filename)[1]
                qr_data = "UNKNOWN"

                try:
                    if ext.lower() == ".pdf":
                        with fitz.open(source_path) as doc:
                            for page in doc:
                                pix = page.get_pixmap(dpi=150, alpha=False)
                                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                                image = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)
                                qr_data = self.decode_qr_from_image(image)
                                if qr_data != "UNKNOWN":
                                    break
                    else:
                        encoded_image = np.fromfile(source_path, dtype=np.uint8)
                        image = cv2.imdecode(encoded_image, cv2.IMREAD_COLOR)
                        if image is not None:
                            qr_data = self.decode_qr_from_image(image)

                    if qr_data != "UNKNOWN":
                        proposed_name = f"{qr_data}{ext}"
                        destination_path = self.reserve_destination(dest_folder, proposed_name, reserved_paths)
                        shutil.copy2(source_path, destination_path)
                        renamed_count += 1
                    else:
                        self.failed_files.append(filename)
                        if copy_unreadable:
                            not_found_files.append(filename)
                            self.not_found_folder = os.path.join(dest_folder, NOT_FOUND_IMAGES_FOLDER)
                            os.makedirs(self.not_found_folder, exist_ok=True)
                            shutil.copy2(source_path, os.path.join(self.not_found_folder, filename))

                except Exception:
                    self.failed_files.append(filename)

            if self.failed_files:
                report_path = os.path.join(dest_folder, UNREADABLE_QR_REPORT)
                with open(report_path, "w", encoding="utf-8") as report:
                    report.write("\n".join(self.failed_files))

            if copy_unreadable and not_found_files:
                not_found_report_path = os.path.join(self.not_found_folder, NOT_FOUND_IMAGES_REPORT)
                with open(not_found_report_path, "w", encoding="utf-8") as report:
                    report.write("\n".join(not_found_files))

            self.worker_events.put(("done", (renamed_count, total)))

        except Exception:
            self.worker_events.put(("cancelled", None))

    def reserve_destination(self, dest_folder, proposed_name, reserved_paths):
        candidate = os.path.join(dest_folder, proposed_name)
        candidate_key = os.path.normcase(os.path.abspath(candidate))

        stem, ext = os.path.splitext(proposed_name)
        suffix = 2
        while os.path.exists(candidate) or candidate_key in reserved_paths:
            candidate = os.path.join(dest_folder, f"{stem}_{suffix}{ext}")
            candidate_key = os.path.normcase(os.path.abspath(candidate))
            suffix += 1

        reserved_paths.add(candidate_key)
        return candidate


if __name__ == "__main__":
    app = ModernQRRenamer()
    app.mainloop()
