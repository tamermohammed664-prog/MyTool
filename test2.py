import os
import shutil
import threading
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image


class FileSearcherApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # 1. طول البرنامج 750 (مقصوص من تحت)
        self.title("File Searcher Pro - Turbo Mode")
        self.geometry("650x750")
        ctk.set_appearance_mode("dark")

        # تحسين جودة الأيقونة
        try:
            if os.path.exists('my_icon.ico'):
                pil_image = Image.open('my_icon.ico')
                ctk_icon = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(64, 64))
                self.after(200, lambda: self.wm_iconphoto(True, ctk_icon))
        except Exception:
            pass

        self.list_names_path = ctk.StringVar()
        self.search_folder_path = ctk.StringVar()
        self.destination_folder_path = ctk.StringVar()
        self.extension_filter = ctk.StringVar(value=".jpg, .jpeg, .pdf, .tif, .tiff, .png")

        # --- الواجهة ---
        self.create_section_label("Path Configuration")

        for var, label, cmd in [
            (self.list_names_path, "Names List", self.browse_names_list),
            (self.search_folder_path, "Search Path", self.browse_search_folder),
            (self.destination_folder_path, "Dest Path", self.browse_dest_folder)
        ]:
            frame = self.create_row_frame()
            ctk.CTkEntry(frame, textvariable=var, width=450).pack(side="left", padx=5)
            ctk.CTkButton(frame, text=label, command=cmd, width=100).pack(side="left")

        self.create_section_label("Search & Filter Options")

        # إبعاد الاختيارات عن بعضها (pady=5) لتقليل الزحمة
        self.organize_by_customer = ctk.CTkCheckBox(self, text="Organize in Customer Folders")
        self.organize_by_customer.pack(anchor="w", padx=30, pady=6)

        self.move_files = ctk.CTkCheckBox(self, text="Move Files (Default: Copy)")
        self.move_files.pack(anchor="w", padx=30, pady=6)

        # Exact Match غير مفعل افتراضياً
        self.exact_match = ctk.CTkCheckBox(self, text="Exact Filename Match")
        self.exact_match.pack(anchor="w", padx=30, pady=6)

        self.include_subfolders = ctk.CTkCheckBox(self, text="Search in Subfolders")
        self.include_subfolders.select()
        self.include_subfolders.pack(anchor="w", padx=30, pady=6)

        filter_frame = self.create_row_frame()
        ctk.CTkLabel(filter_frame, text="Extensions:").pack(side="left", padx=5)
        ctk.CTkEntry(filter_frame, textvariable=self.extension_filter, width=220).pack(side="left", padx=5)
        self.case_sensitive = ctk.CTkCheckBox(filter_frame, text="Case Sensitive")
        self.case_sensitive.pack(side="left", padx=10)

        # زر التشغيل
        btn_frame = self.create_row_frame()
        self.start_btn = ctk.CTkButton(btn_frame, text="START TURBO SEARCH", fg_color="#2b719e",
                                       hover_color="#1a4d6d", command=self.start_thread, height=45,
                                       font=("Arial", 14, "bold"))
        self.start_btn.pack(pady=15, fill="x", padx=10)

        self.status_label = ctk.CTkLabel(self, text="Status: Ready", anchor="w")
        self.status_label.pack(fill="x", padx=30)

        self.progress = ctk.CTkProgressBar(self, width=550)
        self.progress.set(0)
        self.progress.pack(pady=5)

        # تصغير صندوق اللوج لتقليل المساحة تحت
        self.log_area = ctk.CTkTextbox(self, width=580, height=140, font=("Consolas", 12))
        self.log_area.pack(pady=5, padx=20)

        # توقيع تامر إسماعيل (كبير وواضح)
        footer_label = ctk.CTkLabel(self, text="Made by Tamer Ismail", font=("Arial", 15, "bold", "italic"),
                                    text_color="#7f8c8d")
        footer_label.pack(side="bottom", pady=15)

    def create_section_label(self, text):
        ctk.CTkLabel(self, text=text, font=("Arial", 13, "bold"), text_color="#5dade2").pack(anchor="w", padx=25,
                                                                                             pady=(15, 5))

    def create_row_frame(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=3)
        return frame

    def log(self, message):
        self.log_area.insert("end", f"{message}\n")
        self.log_area.see("end")

    def browse_names_list(self):
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if path: self.list_names_path.set(path)

    def browse_search_folder(self):
        path = filedialog.askdirectory()
        if path: self.search_folder_path.set(path)

    def browse_dest_folder(self):
        path = filedialog.askdirectory()
        if path: self.destination_folder_path.set(path)

    def start_thread(self):
        if not all([self.list_names_path.get(), self.search_folder_path.get(), self.destination_folder_path.get()]):
            messagebox.showwarning("Warning", "Please select all required paths!")
            return
        self.start_btn.configure(state="disabled")
        self.log_area.delete("0.0", "end")
        threading.Thread(target=self.run_turbo_search, daemon=True).start()

    def run_turbo_search(self):
        try:
            self.status_label.configure(text="Status: Indexing files...")
            file_index = {}
            search_root = self.search_folder_path.get()
            exts_list = [e.strip().lower() for e in self.extension_filter.get().split(',')]

            walk_gen = os.walk(search_root) if self.include_subfolders.get() else [next(os.walk(search_root))]

            for root, _, files in walk_gen:
                for file in files:
                    if any(file.lower().endswith(ext) for ext in exts_list):
                        name_key = file if self.case_sensitive.get() else file.lower()
                        if name_key not in file_index:
                            file_index[name_key] = []
                        file_index[name_key].append(os.path.join(root, file))

            with open(self.list_names_path.get(), 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]

            dest_root = self.destination_folder_path.get()
            missing_items, found_count = [], 0
            total = len(lines)

            for i, line in enumerate(lines):
                query, customer = [x.strip() for x in line.split(',', 1)] if (
                            self.organize_by_customer.get() and ',' in line) else (line, None)
                self.status_label.configure(text=f"Matching: {query}")

                q_key = query if self.case_sensitive.get() else query.lower()
                matched_files = []

                if self.exact_match.get():
                    for ext in exts_list:
                        full_key = f"{q_key}{ext}"
                        if full_key in file_index:
                            matched_files.extend(file_index[full_key])
                else:
                    for key in file_index:
                        if q_key in key:
                            matched_files.extend(file_index[key])

                if matched_files:
                    for src_path in matched_files:
                        f_name = os.path.basename(src_path)
                        f_dir = os.path.join(dest_root, customer) if customer else dest_root
                        if customer and not os.path.exists(f_dir): os.makedirs(f_dir)
                        d_path = os.path.join(f_dir, f_name)
                        shutil.move(src_path, d_path) if self.move_files.get() else shutil.copy2(src_path, d_path)
                        self.log(f"[FOUND] {f_name}")
                    found_count += 1
                else:
                    self.log(f"[MISSING] {query}")
                    missing_items.append(line)
                self.progress.set((i + 1) / total)

            if missing_items:
                with open(os.path.join(dest_root, "missing_files.txt"), 'w', encoding='utf-8') as f:
                    f.write("\n".join(missing_items))

            messagebox.showinfo("Done", f"Found {found_count}/{total}")
        except Exception as e:
            self.log(f"ERROR: {str(e)}")
        finally:
            self.start_btn.configure(state="normal")
            self.status_label.configure(text="Status: Ready")


if __name__ == "__main__":
    app = FileSearcherApp()
    app.mainloop()