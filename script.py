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
        self.geometry("620x600")
        self.resizable(False, False)

        # Header
        self.label = ctk.CTkLabel(self, text="Image Batch Renamer", font=("Helvetica", 28, "bold"))
        self.label.pack(pady=(35, 5))
        
        self.subtitle = ctk.CTkLabel(self, text="Professional tool for high-volume renaming", font=("Helvetica", 14), text_color="#7f8c8d")
        self.subtitle.pack(pady=(0, 25))

        # Input Rows
        self.folder_path = ""
        self.txt_path = ""
        self.create_row("Select Folder", self.select_folder, "lbl_folder", "#1f538d")
        self.create_row("Select Mapping File", self.select_txt, "lbl_txt", "#1e8449")

        # Segmented Progress Bar Look (Simulated as blocks)
        self.prog_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.prog_frame.pack(pady=(30, 0))
        
        self.progress = ctk.CTkProgressBar(self.prog_frame, width=420, height=14, 
                                           corner_radius=2, 
                                           progress_color="#f39c12", 
                                           fg_color="#2c3e50")
        self.progress.set(0)
        self.progress.pack()

        # Resized Start Button (Compact)
        self.btn_start = ctk.CTkButton(self, text="START PROCESS", command=self.run_process, 
                                       height=45, width=200,
                                       font=("Arial", 16, "bold"),
                                       fg_color="#212f3d", 
                                       border_width=1,
                                       border_color="#566573",
                                       hover_color="#2c3e50")
        self.btn_start.pack(pady=40)

        # Bottom Signature Plate (Matching Image)
        self.sig_frame = ctk.CTkFrame(self, height=50, fg_color="#2d3436", corner_radius=0)
        self.sig_frame.pack(side="bottom", fill="x")
        
        self.signature = ctk.CTkLabel(self.sig_frame, text="Created by Mr. Tamer Ismail", 
                                      font=("Times New Roman", 20, "italic"), 
                                      text_color="#bdc3c7")
        self.signature.pack(pady=10)

    def create_row(self, btn_txt, cmd, lbl_name, color):
        frame = ctk.CTkFrame(self, fg_color="#1c2833", corner_radius=10)
        frame.pack(pady=8, padx=40, fill="x")
        btn = ctk.CTkButton(frame, text=btn_txt, command=cmd, width=150, fg_color=color)
        btn.pack(side="left", padx=15, pady=12)
        lbl = ctk.CTkLabel(frame, text="No selection made", font=("Helvetica", 12), text_color="#95a5a6")
        lbl.pack(side="left", padx=10)
        setattr(self, lbl_name, lbl)

    def select_folder(self):
        self.folder_path = filedialog.askdirectory()
        if self.folder_path: self.lbl_folder.configure(text=f".../{os.path.basename(self.folder_path)}", text_color="#3498db")

    def select_txt(self):
        self.txt_path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if self.txt_path: self.lbl_txt.configure(text=os.path.basename(self.txt_path), text_color="#2ecc71")

    def run_process(self):
        if not self.folder_path or not self.txt_path: return
        threading.Thread(target=self.start_renaming, daemon=True).start()

    def start_renaming(self):
        try:
            self.btn_start.configure(state="disabled")
            with open(self.txt_path, 'r', encoding='utf-8') as f:
                mapping = {}
                for line in f:
                    if ',' in line:
                        old, new = line.strip().split(',', 1)
                        mapping[old.strip()] = new.strip()

            files = [f for f in os.listdir(self.folder_path) if os.path.isfile(os.path.join(self.folder_path, f))]
            total = len(files)
            for i, f_name in enumerate(files):
                name, ext = os.path.splitext(f_name)
                if name in mapping:
                    os.rename(os.path.join(self.folder_path, f_name), 
                              os.path.join(self.folder_path, f"{mapping[name]}{ext}"))
                self.progress.set((i + 1) / total)
                self.update_idletasks()
            
            messagebox.showinfo("Success", "Images renamed successfully!")
        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            self.btn_start.configure(state="normal")
            self.progress.set(0)

if __name__ == "__main__":
    app = ModernRenamer()
    app.mainloop()
