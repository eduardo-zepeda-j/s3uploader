import customtkinter as ctk
from tkinter import messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES
from core.i18n import t
from ui import design
from ui.design import Color, Type, Space, RADIUS, RADIUS_SM

class LoginWindow(ctk.CTkToplevel, TkinterDnD.DnDWrapper):
    def __init__(self, master, on_success_callback):
        super().__init__(master)
        self.title(t("login_title"))
        self.geometry("420x560")
        self.resizable(False, False)
        self.configure(fg_color=Color.BG)
        self.grab_set()

        self.on_success = on_success_callback

        try:
            self.TkdndVersion = master.TkdndVersion
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.on_drop)
        except Exception as e:
            print("No DnD mode available:", e)

        # Generous outer padding, single column, strong vertical rhythm
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=Space.XXL, pady=Space.XXL)

        # Brand
        brand = ctk.CTkFrame(container, fg_color="transparent")
        brand.pack(anchor="w", pady=(0, Space.XL))
        ctk.CTkLabel(brand, text="s3", font=design.font(26, "bold"),
                     text_color=Color.ACCENT).pack(side="left")
        ctk.CTkLabel(brand, text="Uploader", font=design.font(26, "bold"),
                     text_color=Color.TEXT).pack(side="left", padx=(2, 0))

        ctk.CTkLabel(container, text=t("login_subtitle"), font=Type.BODY,
                     text_color=Color.TEXT_MUTED, justify="left", anchor="w").pack(fill="x", pady=(0, Space.LG))

        self.btn_csv = ctk.CTkButton(
            container, text=" " + t("load_csv_btn"), image=design.icon("upload", 16, Color.ON_ACCENT),
            command=self.load_csv, **design.primary_button_kwargs())
        self.btn_csv.pack(fill="x", pady=(0, Space.LG))

        # Divider with centered label
        sep = ctk.CTkFrame(container, fg_color="transparent")
        sep.pack(fill="x", pady=Space.SM)
        ctk.CTkFrame(sep, height=1, fg_color=Color.LINE).pack(side="left", fill="x", expand=True, pady=10)
        ctk.CTkLabel(sep, text=t("or_manual_entry"), font=Type.CAPTION,
                     text_color=Color.TEXT_FAINT).pack(side="left", padx=Space.SM)
        ctk.CTkFrame(sep, height=1, fg_color=Color.LINE).pack(side="left", fill="x", expand=True, pady=10)

        entry_kwargs = dict(height=38, corner_radius=RADIUS, border_color=Color.LINE_STRONG,
                            border_width=1, fg_color=Color.SURFACE, font=Type.BODY)
        self.entry_ak = ctk.CTkEntry(container, placeholder_text=t("ph_access_key"), show="*", **entry_kwargs)
        self.entry_ak.pack(fill="x", pady=Space.SM)
        self.entry_sk = ctk.CTkEntry(container, placeholder_text=t("ph_secret_key"), show="*", **entry_kwargs)
        self.entry_sk.pack(fill="x", pady=Space.SM)
        self.entry_rg = ctk.CTkEntry(container, placeholder_text=t("ph_region"), **entry_kwargs)
        self.entry_rg.pack(fill="x", pady=Space.SM)

        self.btn_connect = ctk.CTkButton(
            container, text=t("btn_connect"), command=self.attempt_login, **design.primary_button_kwargs())
        self.btn_connect.pack(fill="x", pady=(Space.LG, 0))

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
