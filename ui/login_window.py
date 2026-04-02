import customtkinter as ctk
from tkinter import messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES
from core.i18n import t

class LoginWindow(ctk.CTkToplevel, TkinterDnD.DnDWrapper):
    def __init__(self, master, on_success_callback):
        super().__init__(master)
        self.title(t("login_title"))
        self.geometry("400x450")
        self.resizable(False, False)
        self.grab_set()
        
        self.on_success = on_success_callback
        
        try:
            self.TkdndVersion = master.TkdndVersion
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.on_drop)
        except Exception as e:
            print("No DnD mode available:", e)
        
        ctk.CTkLabel(self, text=t("login_subtitle"), font=("Helvetica", 16, "bold")).pack(pady=20)
        
        self.btn_csv = ctk.CTkButton(self, text=t("load_csv_btn"), command=self.load_csv)
        self.btn_csv.pack(pady=10)
        
        ctk.CTkLabel(self, text=t("or_manual_entry"), font=("Helvetica", 12)).pack(pady=(10, 0))
        
        self.entry_ak = ctk.CTkEntry(self, placeholder_text=t("ph_access_key"), show="*")
        self.entry_ak.pack(pady=10, padx=20, fill="x")
        self.entry_sk = ctk.CTkEntry(self, placeholder_text=t("ph_secret_key"), show="*")
        self.entry_sk.pack(pady=10, padx=20, fill="x")
        self.entry_rg = ctk.CTkEntry(self, placeholder_text=t("ph_region"))
        self.entry_rg.pack(pady=10, padx=20, fill="x")
        
        self.btn_connect = ctk.CTkButton(self, text=t("btn_connect"), command=self.attempt_login)
        self.btn_connect.pack(pady=20, padx=20)
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_drop(self, event):
        data = getattr(event, 'data', '')
        if data.startswith('{') and data.endswith('}'):
            paths = [data.strip('{}')]
        else:
            paths = [data]
            
        if paths and paths[0].lower().endswith('.csv'):
            self.process_csv_path(paths[0])
        else:
            messagebox.showinfo("Error", t("err_drop_csv_only"), parent=self)

    def load_csv(self):
        from tkinter import filedialog
        file_path = filedialog.askopenfilename(filetypes=[(t("csv_files"), "*.csv")])
        if file_path:
            self.process_csv_path(file_path)

    def process_csv_path(self, file_path):
        try:
            import csv
            with open(file_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                headers = next(reader, None)
                if not headers: return
                ak_idx, sk_idx = -1, -1
                for i, h in enumerate(headers):
                    val = h.lower()
                    if "access" in val and "key" in val and "id" in val: ak_idx = i
                    elif "secret" in val and "key" in val: sk_idx = i
                if ak_idx != -1 and sk_idx != -1:
                    row = next(reader, None)
                    if row:
                        self.entry_ak.delete(0, "end")
                        self.entry_ak.insert(0, row[ak_idx].strip())
                        self.entry_sk.delete(0, "end")
                        self.entry_sk.insert(0, row[sk_idx].strip())
                        messagebox.showinfo(t("title_credentials"), t("msg_credentials_loaded"), parent=self)
        except Exception as e:
            messagebox.showerror(t("err_csv"), str(e), parent=self)

    def attempt_login(self):
        ak = self.entry_ak.get().strip()
        sk = self.entry_sk.get().strip()
        rg = self.entry_rg.get().strip()
        if not ak or not sk: return
        if not rg: rg = "us-east-1"
        self.on_success(ak, sk, rg)
        self.destroy()

    def on_close(self):
        import os
        os._exit(0)
