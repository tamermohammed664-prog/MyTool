import os
import shutil
import threading
from tkinter import filedialog, messagebox
import customtkinter as ctk


class FileSearcherApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("File Searcher")
        self.geometry("650x750")

        # Variables
        self.list_names_path = ctk.StringVar()
        self.search_folder_path = ctk.StringVar()
        self.destination_folder_path = ctk.StringVar()
        self.extension_filter = ctk.StringVar(value=".jpg, .jpeg, .pdf, .tif, .tiff, .png")

        # --- UI Layout ---

        # 1. List of Names
        self.create_section_label("List of Names (Text File)")
        frame1 = self.create_row_frame()
        ctk.CTkEntry(frame1, textvariable=self.list_names_path, width=450).pack(side="left", padx=5)
        ctk.CTkButton(frame1, text="Browse", command=self.browse_names_list, width=80).pack(side="left")

        # 2. Search Folder
        self.create_section_label("Search folder")
        frame2 = self.create_row_frame()
        ctk.CTkEntry(frame2, textvariable=self.search_folder_path, width=450).pack(side="left", padx=5)
        ctk.CTkButton(frame2, text="Browse", command=self.browse_search_folder, width=80).pack(side="left")

        # 3. Destination folder
        self.create_section_label("Destination folder")
        frame3 = self.create_row_frame()
        ctk.CTkEntry(frame3, textvariable=self.destination_folder_path, width=450).pack(side="left", padx=5)
        ctk.CTkButton(frame3, text="Browse", command=self.browse_dest_folder, width=80).pack(side="left")

        # 4. Filters & Options
        filter_frame = self.create_row_frame()
        ctk.CTkLabel(filter_frame, text="File Type Filter (ext):").pack(side="left", padx=5)
        ctk.CTkEntry(filter_frame, textvariable=self.extension_filter, width=250).pack(side="left", padx=5)
        self.case_sensitive = ctk.CTkCheckBox(filter_frame, text="Case Sensitive")
        self.case_sensitive.pack(side="left", padx=20)

        # 5. Move Checkbox
        move_frame = self.create_row_frame()
        self.move_files = ctk.CTkCheckBox(move_frame, text="Move files instead of copying")
        self.move_files.pack(side="left", padx=5)

        # 6. Search Options
        self.create_section_label("Search Options:")
        self.exact_match = ctk.CTkCheckBox(self, text="Exact filename match (otherwise contains match)")
        self.exact_match.pack(anchor="w", padx=30, pady=2)
        self.include_subfolders = ctk.CTkCheckBox(self, text="Include subfolders")
        self.include_subfolders.select()
        self.include_subfolders.pack(anchor="w", padx=30, pady=2)

        # 7. Action Buttons
        btn_frame = self.create_row_frame()
        self.start_btn = ctk.CTkButton(btn_frame, text="Start Search", fg_color="#2b719e", command=self.start_thread)
        self.start_btn.pack(side="left", padx=10, pady=20)
        self.stop_search = False  # Flag to stop search if needed

        # 8. Status & Progress
        self.status_label = ctk.CTkLabel(self, text="Ready to search", anchor="w")
        self.status_label.pack(fill="x", padx=30)
        self.progress = ctk.CTkProgressBar(self, width=550)
        self.progress.set(0)
        self.progress.pack(pady=10)

        # 9. Log Area
        self.log_area = ctk.CTkTextbox(self, width=580, height=180)
        self.log_area.pack(pady=10, padx=20)

    # --- UI Helpers ---
    def create_section_label(self, text):
        lbl = ctk.CTkLabel(self, text=text, font=("Arial", 12, "bold"))
        lbl.pack(anchor="w", padx=25, pady=(15, 2))

    def create_row_frame(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=5)
        return frame

    def log(self, message):
        self.log_area.insert("end", f"{message}\n")
        self.log_area.see("end")

    # --- Browser Functions ---
    def browse_names_list(self):
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if path: self.list_names_path.set(path)

    def browse_search_folder(self):
        path = filedialog.askdirectory()
        if path: self.search_folder_path.set(path)

    def browse_dest_folder(self):
        path = filedialog.askdirectory()
        if path: self.destination_folder_path.set(path)

    # --- Logic ---
    def start_thread(self):
        # Basic Validation
        if not all([self.list_names_path.get(), self.search_folder_path.get(), self.destination_folder_path.get()]):
            messagebox.showwarning("Warning", "Please select all required paths!")
            return

        self.start_btn.configure(state="disabled")
        self.log_area.delete("0.0", "end")
        threading.Thread(target=self.run_search, daemon=True).start()

    def run_search(self):
        try:
            # 1. Load names from file
            with open(self.list_names_path.get(), 'r', encoding='utf-8') as f:
                names = [line.strip() for line in f if line.strip()]

            if not names:
                self.log("Error: List of names is empty.")
                self.start_btn.configure(state="normal")
                return

            # 2. Prepare extensions
            exts = [e.strip().lower() for e in self.extension_filter.get().split(',')]

            search_root = self.search_folder_path.get()
            dest_root = self.destination_folder_path.get()

            total = len(names)
            found_count = 0

            self.log(f"Started searching for {total} items...")

            for i, name in enumerate(names):
                self.status_label.configure(text=f"Searching for: {name}")
                is_found = False

                # Search logic
                walk_gen = os.walk(search_root) if self.include_subfolders.get() else [next(os.walk(search_root))]

                for root, dirs, files in walk_gen:
                    for file in files:
                        file_lower = file if self.case_sensitive.get() else file.lower()
                        name_query = name if self.case_sensitive.get() else name.lower()

                        # Check Match
                        match = (name_query == os.path.splitext(file_lower)[0]) if self.exact_match.get() else (
                                    name_query in file_lower)

                        if match:
                            # Check Extension
                            if any(file.lower().endswith(ext) for ext in exts):
                                src_path = os.path.join(root, file)
                                # Operation: Move or Copy
                                if self.move_files.get():
                                    shutil.move(src_path, os.path.join(dest_root, file))
                                    self.log(f"[MOVED] {file}")
                                else:
                                    shutil.copy2(src_path, os.path.join(dest_root, file))
                                    self.log(f"[COPIED] {file}")

                                is_found = True
                                found_count += 1
                                break  # Stop searching for this specific name once found
                    if is_found: break

                if not is_found:
                    self.log(f"[NOT FOUND] {name}")

                # Update Progress
                self.progress.set((i + 1) / total)

            self.log("-" * 30)
            self.log(f"Finished. Found: {found_count}/{total}")
            self.status_label.configure(text="Task Completed")
            messagebox.showinfo("Done", f"Search completed.\nFound {found_count} files.")

        except Exception as e:
            self.log(f"CRITICAL ERROR: {str(e)}")
            messagebox.showerror("Error", str(e))

        self.start_btn.configure(state="normal")


if __name__ == "__main__":
    app = FileSearcherApp()
    app.mainloop()