import os
import shutil
import threading
from tkinter import filedialog, messagebox
import customtkinter as ctk


class FileSearcherApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("File Searcher Pro - Turbo Mode")
        self.geometry("620x730")
        ctk.set_appearance_mode("dark")
        self.configure(fg_color="#1a1a1a")

        try:
            if os.path.exists('my_icon.ico'):
                self.after(200, lambda: self.iconbitmap('my_icon.ico'))
        except Exception:
            pass

        self.list_names_path = ctk.StringVar()
        self.search_folder_path = ctk.StringVar()
        self.destination_folder_path = ctk.StringVar()
        self.extension_filter = ctk.StringVar(value=".jpg, .jpeg, .pdf, .tif, .tiff, .png")

        self.create_section_label("Path Configuration").pack(anchor="w", padx=25, pady=(12, 5))

        for var, label, cmd in [
            (self.list_names_path, "Names List", self.browse_names_list),
            (self.search_folder_path, "Search Path", self.browse_search_folder),
            (self.destination_folder_path, "Dest Path", self.browse_dest_folder)
        ]:
            frame = ctk.CTkFrame(self, fg_color="transparent")
            frame.pack(fill="x", padx=20, pady=6)
            ctk.CTkEntry(frame, textvariable=var, width=400, height=28, fg_color="#333333").pack(side="left", padx=5)
            ctk.CTkButton(frame, text=label, command=cmd, width=90, height=28, fg_color="#2b719e").pack(side="left")

        self.create_section_label("Search & Filter Options").pack(anchor="w", padx=25, pady=(8, 4))

        self.organize_by_customer = ctk.CTkCheckBox(self, text="Organize in Customer Folders", font=("Arial", 11))
        self.organize_by_customer.pack(anchor="w", padx=35, pady=2)

        self.move_files = ctk.CTkCheckBox(self, text="Move Files (Default: Copy)", font=("Arial", 11))
        self.move_files.pack(anchor="w", padx=35, pady=2)

        self.exact_match = ctk.CTkCheckBox(self, text="Exact Filename Match", font=("Arial", 11))
        self.exact_match.pack(anchor="w", padx=35, pady=2)

        self.include_subfolders = ctk.CTkCheckBox(self, text="Search in Subfolders", font=("Arial", 11))
        self.include_subfolders.select()
        self.include_subfolders.pack(anchor="w", padx=35, pady=2)

        ext_frame = ctk.CTkFrame(self, fg_color="transparent")
        ext_frame.pack(fill="x", padx=25, pady=8)
        ctk.CTkLabel(ext_frame, text="Extensions:", font=("Arial", 11)).pack(side="left", padx=5)
        ctk.CTkEntry(ext_frame, textvariable=self.extension_filter, width=180, height=25, fg_color="#333333").pack(
            side="left", padx=5)
        self.case_sensitive = ctk.CTkCheckBox(ext_frame, text="Case Sensitive", font=("Arial", 10))
        self.case_sensitive.pack(side="left", padx=10)

        self.start_btn = ctk.CTkButton(self, text="START TURBO SEARCH", fg_color="#2b719e",
                                       height=38, font=("Arial", 13, "bold"), command=self.start_thread)
        self.start_btn.pack(pady=10, fill="x", padx=40)

        self.status_label = ctk.CTkLabel(self, text="Status: Ready", anchor="w", font=("Arial", 10))
        self.status_label.pack(fill="x", padx=45)

        self.progress = ctk.CTkProgressBar(self, width=540, height=8, progress_color="#2b719e")
        self.progress.set(0)
        self.progress.pack(pady=4)

        self.log_area = ctk.CTkTextbox(self, width=560, height=110, fg_color="#121212", font=("Consolas", 10))
        self.log_area.pack(pady=5, padx=20)

        self.footer = ctk.CTkLabel(self, text="Created by Mr. Tamer Ismail",
                                   font=("Monotype Corsiva", 20, "italic"),
                                   text_color="#5dade2")
        self.footer.pack(side="bottom", pady=10)

    def create_section_label(self, text):
        return ctk.CTkLabel(self, text=text, font=("Arial", 12, "bold"), text_color="#5dade2")

    def log(self, message):
        self.log_area.insert("end", f"{message}\n")
        self.log_area.see("end")

    def browse_names_list(self):
        p = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if p: self.list_names_path.set(p)

    def browse_search_folder(self):
        p = filedialog.askdirectory()
        if p: self.search_folder_path.set(p)

    def browse_dest_folder(self):
        p = filedialog.askdirectory()
        if p: self.destination_folder_path.set(p)

    def start_thread(self):
        if not all([self.list_names_path.get(), self.search_folder_path.get(), self.destination_folder_path.get()]):
            messagebox.showwarning("Warning", "Please select all paths!")
            return
        self.start_btn.configure(state="disabled")
        self.log_area.delete("0.0", "end")
        threading.Thread(target=self.run_turbo_search, daemon=True).start()

    def run_turbo_search(self):
        try:
            self.log("Indexing files...")
            file_index = {}
            search_root = self.search_folder_path.get()
            exts = [e.strip().lower() for e in self.extension_filter.get().split(',')]

            walk_gen = os.walk(search_root) if self.include_subfolders.get() else [next(os.walk(search_root))]

            for root, _, files in walk_gen:
                for f in files:
                    if any(f.lower().endswith(e) for e in exts):
                        k = f.lower()
                        if k not in file_index: file_index[k] = []
                        file_index[k].append(os.path.join(root, f))

            with open(self.list_names_path.get(), 'r', encoding='utf-8') as f:
                raw_lines = [l.strip() for l in f if l.strip()]

            dest = self.destination_folder_path.get()
            total, found, missing_list = len(raw_lines), 0, []

            for i, line in enumerate(raw_lines):
                query, cust = [x.strip() for x in line.split(',', 1)] if (
                            self.organize_by_customer.get() and ',' in line) else (line, None)
                q_key = query.lower()
                matches = []

                if self.exact_match.get():
                    for e in exts:
                        if f"{q_key}{e}" in file_index: matches.extend(file_index[f"{q_key}{e}"])
                else:
                    for k in file_index:
                        if q_key in k: matches.extend(file_index[k])

                if matches:
                    for src in matches:
                        d_p = os.path.join(dest, cust) if cust else dest
                        if cust and not os.path.exists(d_p): os.makedirs(d_p)
                        shutil.move(src, os.path.join(d_p, os.path.basename(
                            src))) if self.move_files.get() else shutil.copy2(src,
                                                                              os.path.join(d_p, os.path.basename(src)))
                        self.log(f"[OK] {os.path.basename(src)}")
                    found += 1
                else:
                    self.log(f"[MISS] {query}")
                    missing_list.append(line)
                self.progress.set((i + 1) / total)

            if missing_list:
                m_file = os.path.join(dest, "Missing_Files.txt")
                with open(m_file, 'w', encoding='utf-8') as mf:
                    mf.write("\n".join(missing_list))
                self.log("Missing list saved to Missing_Files.txt")

            summary_msg = f"Search completed!\n\nFiles found: {found}\nFiles not found: {len(missing_list)}\n\nCheck the results panel for details."
            messagebox.showinfo("Search Completed", summary_msg)

        except Exception as e:
            self.log(f"ERROR: {e}")
        finally:
            self.start_btn.configure(state="normal")


if __name__ == "__main__":
    app = FileSearcherApp()
    app.mainloop()