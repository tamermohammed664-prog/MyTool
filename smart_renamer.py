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
import easyocr

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
ARABIC_LETTER_TRANSLATION = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي"})
FIELD_KEYWORDS = (
    ("اذنتسليم", "اذنالتسليم", "تسليممسعر"),
    ("امرالتوريد", "امرتوريد"),
    ("رقمالفاتوره", "رقمالفاتورة", "الفاتوره", "الفاتورة"),
)
DOCUMENT_NUMBER_LENGTH = 8
FIELD_ROIS = (
    (0.25, 0.01, 0.72, 0.11),
    (0.72, 0.19, 0.88, 0.29),
    (0.62, 0.29, 0.98, 0.37),
)


class SmartRenamer(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("SMART RENAMER")
        self.geometry("650x640")
        self.resizable(False, False)

        self.label = ctk.CTkLabel(self, text="SMART RENAMER", font=("Helvetica Neue", 28, "bold"))
        self.label.pack(pady=(25, 5))

        self.subtitle = ctk.CTkLabel(
            self,
            text="Template ROI Auto Renamer (Images & PDFs)",
            font=("Helvetica Neue", 13),
            text_color="#7f8c8d",
        )
        self.subtitle.pack(pady=(0, 20))

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
            btn_color="#27ae60",
        )

        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_frame.pack(pady=(20, 0))

        self.progress = ctk.CTkProgressBar(
            self.progress_frame,
            width=400,
            height=12,
            corner_radius=2,
            progress_color="#f39c12",
            fg_color="#2c3e50",
        )
        self.progress.set(0)
        self.progress.pack()

        self.lbl_status = ctk.CTkLabel(self, text="Ready", font=("Helvetica", 12), text_color="#bdc3c7")
        self.lbl_status.pack(pady=(10, 0))

        self.btn_start = ctk.CTkButton(
            self,
            text="START PROCESS",
            command=self.run_process,
            height=50,
            width=300,
            font=("Arial", 18, "bold"),
            fg_color="#212f3d",
            border_width=1,
            border_color="#566573",
            hover_color="#2c3e50",
        )
        self.btn_start.pack(pady=25)

        self.signature_frame = ctk.CTkFrame(self, fg_color="#34495e", height=40, corner_radius=0)
        self.signature_frame.pack(side="bottom", fill="x")
        self.signature = ctk.CTkLabel(
            self.signature_frame,
            text="Created by Mr. Tamer Ismail",
            font=("Times New Roman", 18, "italic"),
            text_color="#bdc3c7",
        )
        self.signature.pack(pady=5)

        self.folder_path = ""
        self.selected_file = ""
        self.output_path = ""
        self.reader = None
        self.worker_events = queue.Queue()
        self.preview_window = None
        self.preview_items = []
        self.after(50, self.process_worker_events)

    def create_input_field(
        self,
        btn_text,
        command,
        label_attr,
        default_text,
        btn_color="#1f538d",
        secondary_button=None,
    ):
        frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#1c2833")
        frame.pack(pady=8, padx=50, fill="x")

        btn = ctk.CTkButton(frame, text=btn_text, command=command, width=140, fg_color=btn_color)
        btn.pack(side="left", padx=15, pady=10)
        if secondary_button:
            secondary = ctk.CTkButton(
                frame,
                text=secondary_button[0],
                command=secondary_button[1],
                width=105,
                fg_color="#34495e",
            )
            secondary.pack(side="left", padx=(0, 8), pady=10)

        lbl = ctk.CTkLabel(frame, text=default_text, font=("Helvetica", 12), text_color="#95a5a6")
        lbl.pack(side="left", padx=10, fill="x", expand=True)
        setattr(self, label_attr, lbl)

    def select_folder(self):
        selected_folder = filedialog.askdirectory()
        if selected_folder:
            self.selected_file = ""
            self.folder_path = selected_folder
            self.lbl_folder.configure(text=f"Folder: {os.path.basename(self.folder_path)}", text_color="#3498db")

    def select_file(self):
        selected_file = filedialog.askopenfilename(
            filetypes=[("Images and PDFs", "*.jpg *.jpeg *.png *.pdf"), ("All files", "*.*")]
        )
        if selected_file:
            self.selected_file = selected_file
            self.folder_path = ""
            self.lbl_folder.configure(text=f"File: {os.path.basename(selected_file)}", text_color="#3498db")

    def select_output_folder(self):
        self.output_path = filedialog.askdirectory()
        if self.output_path:
            self.lbl_output.configure(text=f"Dst: {os.path.basename(self.output_path)}", text_color="#2ecc71")

    def run_process(self):
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

        self.btn_start.configure(state="disabled", text="Scanning...")
        self.progress.set(0)
        self.lbl_status.configure(text="Preparing scan...")
        threading.Thread(target=self.scan_files, daemon=True).start()

    def init_ocr(self):
        if self.reader is None:
            self.worker_events.put(("status", "Loading OCR model for images (first run may take longer)..."))
            import torch

            torch.set_num_threads(min(4, os.cpu_count() or 1))
            self.reader = easyocr.Reader(["ar", "en"], gpu=False)

    def iter_pdf_pages(self, pdf_path):
        with fitz.open(pdf_path) as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=150, alpha=False)
                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                image = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)
                yield page, image

    def get_pdf_text_numbers(self, page):
        page_rect = page.rect
        words = page.get_text("words", sort=True)
        lines = {}
        for word in words:
            lines.setdefault((word[5], word[6]), []).append(word)

        items = []
        for line in lines.values():
            line.sort(key=lambda word: word[7])
            items.append({
                "text": " ".join(word[4] for word in line),
                "box": (
                    (min(word[0] for word in line) + max(word[2] for word in line)) / 2 / page_rect.width,
                    (min(word[1] for word in line) + max(word[3] for word in line)) / 2 / page_rect.height,
                ),
                "confidence": 1.0,
            })
        return self.match_field_numbers(items)

    def normalize_ocr_text(self, text):
        text = text.translate(DIGIT_TRANSLATION).translate(ARABIC_LETTER_TRANSLATION)
        text = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", text)
        return "".join(character for character in text.lower() if character.isalnum())

    def match_field_numbers(self, items):
        candidates = []
        anchors = [[] for _ in FIELD_KEYWORDS]

        for item_index, item in enumerate(items):
            normalized = self.normalize_ocr_text(item["text"])
            for digit_run in re.finditer(r"\d+", normalized):
                run = digit_run.group()
                if len(run) > DOCUMENT_NUMBER_LENGTH:
                    spans = [
                        (offset, run[offset:offset + DOCUMENT_NUMBER_LENGTH])
                        for offset in range(0, len(run), DOCUMENT_NUMBER_LENGTH)
                    ]
                else:
                    spans = [(0, run)]
                for offset, digits in spans:
                    if len(digits) < 5:
                        continue
                    candidates.append({
                        "value": digits,
                        "item_index": item_index,
                        "start": digit_run.start() + offset,
                        "end": digit_run.start() + offset + len(digits),
                        "box": item["box"],
                        "confidence": item["confidence"],
                    })

            for field_index, keywords in enumerate(FIELD_KEYWORDS):
                positions = [normalized.find(keyword) for keyword in keywords if keyword in normalized]
                if positions:
                    anchors[field_index].append({
                        "item_index": item_index,
                        "position": positions[0],
                        "box": item["box"],
                        "confidence": item["confidence"],
                    })

        for field_index, field_anchors in enumerate(anchors):
            if field_anchors:
                continue
            for seed in items:
                neighbors = [
                    item
                    for item in items
                    if abs(item["box"][1] - seed["box"][1]) <= 0.025
                    and abs(item["box"][0] - seed["box"][0]) <= 0.18
                ]
                combined = "".join(
                    self.normalize_ocr_text(item["text"])
                    for item in sorted(neighbors, key=lambda item: item["box"][0], reverse=True)
                )
                if any(keyword in combined for keyword in FIELD_KEYWORDS[field_index]):
                    field_anchors.append({
                        "item_index": -1,
                        "box": seed["box"],
                        "confidence": seed["confidence"],
                    })

        numbers = []
        used_candidates = set()
        for field_anchors in anchors:
            field_anchors.sort(key=lambda anchor: anchor["confidence"], reverse=True)
            selected = None

            for anchor in field_anchors:
                same_item = [
                    (index, candidate)
                    for index, candidate in enumerate(candidates)
                    if index not in used_candidates and candidate["item_index"] == anchor["item_index"]
                ]
                if same_item:
                    candidate_index, selected = min(
                        same_item,
                        key=lambda entry: abs(
                            (entry[1]["start"] + entry[1]["end"]) / 2 - anchor["position"]
                        ),
                    )
                    used_candidates.add(candidate_index)
                    break

                nearby = []
                for index, candidate in enumerate(candidates):
                    if index in used_candidates:
                        continue
                    delta_x = abs(candidate["box"][0] - anchor["box"][0])
                    delta_y = abs(candidate["box"][1] - anchor["box"][1])
                    if delta_y <= 0.08 and delta_x <= 0.35:
                        score = delta_y * 2 + delta_x - candidate["confidence"] * 0.01
                        nearby.append((score, index, candidate))
                if nearby:
                    _, candidate_index, selected = min(nearby, key=lambda entry: entry[0])
                    used_candidates.add(candidate_index)
                    break

            numbers.append(selected["value"] if selected else "UNKNOWN")

        return tuple(numbers)

    def read_page_numbers(self, image):
        self.init_ocr()
        image_height, image_width = image.shape[:2]
        enhanced_rois = []

        for left, top, right, bottom in FIELD_ROIS:
            x1 = round(image_width * left)
            y1 = round(image_height * top)
            x2 = round(image_width * right)
            y2 = round(image_height * bottom)
            roi = image[y1:y2, x1:x2]
            if roi.size == 0:
                return ("UNKNOWN", "UNKNOWN", "UNKNOWN")

            roi_height, roi_width = roi.shape[:2]
            scale = min(3.0, 1280 / max(roi_height, roi_width))
            roi = cv2.resize(
                roi,
                (max(1, round(roi_width * scale)), max(1, round(roi_height * scale))),
                interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA,
            )
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            enhanced_rois.append(cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray))

        canvas_height = max(roi.shape[0] for roi in enhanced_rois)
        canvas_width = max(roi.shape[1] for roi in enhanced_rois)
        batched_rois = []
        offsets = []
        for roi in enhanced_rois:
            roi_height, roi_width = roi.shape[:2]
            offset_x = (canvas_width - roi_width) // 2
            offset_y = (canvas_height - roi_height) // 2
            canvas = np.full((canvas_height, canvas_width), 255, dtype=np.uint8)
            canvas[offset_y:offset_y + roi_height, offset_x:offset_x + roi_width] = roi
            batched_rois.append(canvas)
            offsets.append((offset_x, offset_y, roi_width, roi_height))

        detections_by_roi = self.reader.readtext_batched(
            batched_rois,
            detail=1,
            paragraph=False,
            min_size=8,
            canvas_size=1280,
            batch_size=4,
            workers=0,
        )
        numbers = []
        for field_index, (detections, offset) in enumerate(zip(detections_by_roi, offsets)):
            offset_x, offset_y, roi_width, roi_height = offset
            items = [
                {
                    "text": text,
                    "box": (
                        (sum(point[0] for point in box) / len(box) - offset_x) / roi_width,
                        (sum(point[1] for point in box) / len(box) - offset_y) / roi_height,
                    ),
                    "confidence": confidence,
                }
                for box, text, confidence in detections
            ]
            numbers.append(self.match_field_numbers(items)[field_index])

        return tuple(numbers)

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
                self.show_preview(payload)
            elif event == "scan_error":
                self.finish_with_error("Scan failed", payload)
            elif event == "status":
                self.lbl_status.configure(text=payload)
            elif event == "apply_progress":
                index, total, filename = payload
                self.progress.set(index / total)
                self.lbl_status.configure(text=f"Renaming ({index}/{total}): {filename}")
            elif event == "apply_done":
                renamed, selected_count, errors = payload
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
                self.worker_events.put(("scan_progress", (index, total, filename)))
                source_path = os.path.join(source_folder, filename)
                ext = os.path.splitext(filename)[1]

                try:
                    if ext.lower() == ".pdf":
                        numbers = ("UNKNOWN", "UNKNOWN", "UNKNOWN")
                        best_numbers = numbers
                        for page, image in self.iter_pdf_pages(source_path):
                            native_numbers = self.get_pdf_text_numbers(page)
                            if "UNKNOWN" not in native_numbers:
                                numbers = native_numbers
                                break

                            ocr_numbers = self.get_target_numbers(image)
                            numbers = tuple(
                                native if native != "UNKNOWN" else ocr
                                for native, ocr in zip(native_numbers, ocr_numbers)
                            )
                            if numbers.count("UNKNOWN") < best_numbers.count("UNKNOWN"):
                                best_numbers = numbers
                            if "UNKNOWN" not in numbers:
                                break
                        else:
                            numbers = best_numbers
                    else:
                        numbers = self.get_target_numbers(cv2.imread(source_path))

                    if "UNKNOWN" in numbers:
                        missing = [
                            label
                            for label, value in zip(("Izn", "Supply", "Invoice"), numbers)
                            if value == "UNKNOWN"
                        ]
                        results.append({
                            "filename": filename,
                            "new_name": "-",
                            "status": f"Not found: {', '.join(missing)}",
                            "eligible": False,
                        })
                        continue

                    proposed_name = f"{numbers[2]} - {numbers[0]} - {numbers[1]}{ext}"
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
                    results.append({
                        "filename": filename,
                        "new_name": "-",
                        "status": f"Error: {ex}",
                        "eligible": False,
                    })

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
        window.transient(self)
        window.grab_set()
        window.protocol("WM_DELETE_WINDOW", self.cancel_preview)

        ctk.CTkLabel(window, text="Review before renaming", font=("Arial", 20, "bold")).pack(pady=(18, 4))
        ctk.CTkLabel(
            window,
            text=f"{ready_count} files ready to rename; {skipped_count} skipped or already named.",
            text_color="#bdc3c7",
        ).pack(pady=(0, 12))

        headers = ctk.CTkFrame(window, fg_color="transparent")
        headers.pack(fill="x", padx=18)
        for text, width in (("Rename", 65), ("Current file", 260), ("Proposed name", 300), ("Result", 210)):
            ctk.CTkLabel(headers, text=text, width=width, anchor="w", font=("Arial", 12, "bold")).pack(
                side="left", padx=4
            )

        rows = ctk.CTkScrollableFrame(window, height=360, fg_color="#17212b")
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
        ctk.CTkButton(actions, text="Cancel", command=self.cancel_preview, fg_color="#566573").pack(
            side="right", padx=(8, 0)
        )
        rename_button = ctk.CTkButton(actions, text="Rename selected", command=self.apply_selected)
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
        self.lbl_status.configure(text="Applying selected names...")
        threading.Thread(target=self.apply_renames, args=(selected,), daemon=True).start()

    def apply_renames(self, selected):
        renamed = 0
        errors = []
        total = len(selected)

        for index, item in enumerate(selected, start=1):
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

        self.worker_events.put(("apply_done", (renamed, total, errors)))

    def finish_apply(self, renamed, selected_count, errors):
        not_selected = sum(item["eligible"] for item in self.preview_items) - selected_count
        self.btn_start.configure(state="normal", text="START PROCESS")
        self.progress.set(0)
        self.lbl_status.configure(text=f"Completed: {renamed} renamed")

        details = f"Renamed {renamed} of {selected_count} selected files."
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
        self.btn_start.configure(state="normal", text="START PROCESS")
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