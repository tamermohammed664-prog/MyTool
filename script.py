import os
import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading

# Appearance Settings
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class ModernRenamer(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Smart Batch Renamer Pro")
        self.geometry("650x580")
        self.resizable(False, False)

        # 1. Header
        self.label = ctk.CTkLabel(self, text="Image Batch Renamer", font=("Helvetica Neue", 28, "bold"))
        self.label.pack(pady=(35, 5))

        self.subtitle = ctk.CTkLabel(self, text="Professional tool for high-volume renaming",
                                     font=("Helvetica Neue", 13), text_color="#7f8c8d")
        self.subtitle.pack(pady=(0, 25))

        # 2. Input Sections (Glassmorphism effect)
        self.create_input_field("Select Folder", self.select_folder, "lbl_folder", "No directory selected")
        self.create_input_field("Select Mapping File", self.select_txt, "lbl_txt", "No .txt file selected",
                                btn_color="#1e8449")

        # 3. Segmented Progress Bar (Custom Look like your image)
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_frame.pack(pady=(30, 0))

        # Creating a segmented look using progress bar properties
        self.progress = ctk.CTkProgressBar(self.progress_frame, width=400, height=12,
                                           corner_radius=2,
                                           progress_color="#f39c12",  # Orange like the image
                                           fg_color="#2c3e50")
        self.progress.set(0)
        self.progress.pack()

        # 4. START PROCESS Button (Resized as requested)
        self.btn_start = ctk.CTkButton(self, text="START PROCESS", command=self.run_process,
                                       height=50, width=300,
                                       font=("Arial", 18, "bold"),
                                       fg_color="#212f3d",
                                       border_width=1,
                                       border_color="#566573",
                                       hover_color="#2c3e50")
        self.btn_start.pack(pady=40)

        # 5. Signature (Matching your image)
        self.signature_frame = ctk.CTkFrame(self, fg_color="#34495e", height=40, corner_radius=0)
        self.signature_frame.pack(side="bottom", fill="x")

        self.signature = ctk.CTkLabel(self.signature_frame, text="Created by Mr. Tamer Ismail",
                                      font=("Times New Roman", 18, "italic"),
                                      text_color="#bdc3c7")
        self.signature.pack(pady=5)

        self.folder_path = ""
        self.txt_path = ""

    def create_input_field(self, btn_text, command, label_attr, default_text, btn_color="#1f538d"):
        frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#1c2833")
        frame.pack(pady=8, padx=50, fill="x")

        btn = ctk.CTkButton(frame, text=btn_text, command=command, width=140, fg_color=btn_color)
        btn.pack(side="left", padx=15, pady=12)

        lbl = ctk.CTkLabel(frame, text=default_text, font=("Helvetica", 12), text_color="#95a5a6")
        lbl.pack(side="left", padx=10)
        setattr(self, label_attr, lbl)

    def select_folder(self):
        self.folder_path = filedialog.askdirectory()
        if self.folder_path:
            self.lbl_folder.configure(text=f"Folder: {os.path.basename(self.folder_path)}", text_color="#3498db")

    def select_txt(self):
        self.txt_path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if self.txt_path:
            self.lbl_txt.configure(text=f"File: {os.path.basename(self.txt_path)}", text_color="#2ecc71")

    def run_process(self):
        if not self.folder_path or not self.txt_path:
            messagebox.showwarning("Alert", "Please select folder and mapping file first.")
            return
        threading.Thread(target=self.start_renaming, daemon=True).start()

    def start_renaming(self):
        try:
            self.btn_start.configure(state="disabled", text="Processing...")

            rename_map = {}
            with open(self.txt_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if ',' in line:
                        old, new = line.strip().split(',', 1)
                        rename_map[old.strip()] = new.strip()

            files = [f for f in os.listdir(self.folder_path) if os.path.isfile(os.path.join(self.folder_path, f))]
            total = len(files)

            for i, filename in enumerate(files):
                name, ext = os.path.splitext(filename)
                if name in rename_map:
                    os.rename(os.path.join(self.folder_path, filename),
                              os.path.join(self.folder_path, f"{rename_map[name]}{ext}"))

                self.progress.set((i + 1) / total)
                self.update_idletasks()

            messagebox.showinfo("Success", "All images have been renamed successfully.")
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            self.btn_start.configure(state="normal", text="START PROCESS")
            self.progress.set(0)


if __name__ == "__main__":
    app = ModernRenamer()
    app.mainloop()