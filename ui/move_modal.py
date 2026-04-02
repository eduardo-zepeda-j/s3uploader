import customtkinter as ctk
from tkinter import messagebox
import threading
import os

class MoveModal(ctk.CTkToplevel):
    def __init__(self, master, s3_manager, items_to_move, origin_bucket, origin_prefix, on_close_callback):
        super().__init__(master)
        self.title("Escoger Destino de Archivos")
        self.geometry("600x500")
        self.resizable(False, False)
        # Block interaction with master UI while modal is open
        self.grab_set()
        
        self.s3_manager = s3_manager
        self.items_to_move = items_to_move # list of tuples: (full_path, type, name)
        self.origin_bucket = origin_bucket
        self.origin_prefix = origin_prefix
        self.on_close_callback = on_close_callback

        # Initial location
        self.current_bucket = origin_bucket
        self.current_prefix = origin_prefix

        self.init_ui()
        self.populate_buckets()
        
        # Load initially starting at current context if a bucket is selected
        if self.current_bucket:
            self.load_directory(self.current_bucket, self.current_prefix)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def init_ui(self):
        # 1. Top - Breadcrumbs
        self.nav_frame = ctk.CTkFrame(self, height=40, fg_color=("#E5E7EB", "#0B0C10"), corner_radius=0)
        self.nav_frame.pack(fill="x", side="top")
        
        self.breadcrumbs_frame = ctk.CTkFrame(self.nav_frame, fg_color="transparent")
        self.breadcrumbs_frame.pack(side="left", padx=10, fill="y")
        
        # 2. Main split: Left Shortcuts, Right Explorer
        self.body_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.body_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.shortcuts_frame = ctk.CTkScrollableFrame(self.body_frame, width=150, fg_color=("#E5E7EB", "#111827"))
        self.shortcuts_frame.pack(side="left", fill="y", padx=(0, 10))

        self.explorer_frame = ctk.CTkScrollableFrame(self.body_frame, fg_color=("#FFFFFF", "#1F2937"))
        self.explorer_frame.pack(side="right", fill="both", expand=True)

        # 3. Bottom - Actions
        self.footer_frame = ctk.CTkFrame(self, height=50, fg_color="transparent")
        self.footer_frame.pack(fill="x", side="bottom", pady=10, padx=10)

        self.lbl_target = ctk.CTkLabel(self.footer_frame, text="Destino: Raíz /", font=("Helvetica Neue", 12, "bold"))
        self.lbl_target.pack(side="left")

        self.btn_move = ctk.CTkButton(self.footer_frame, text="🚚 Mover Aquí", fg_color=("#E5E7EB", "#374151"), hover_color=("#D1D5DB", "#4B5563"), text_color=("#111827", "#F9FAFB"), font=("Helvetica Neue", 14, "bold"), command=self.perform_move)
        self.btn_move.pack(side="right")
        
        self.update_breadcrumbs()

    def update_target_label(self):
        t = f"Destino: {self.current_bucket if self.current_bucket else 'Ninguno'} / {self.current_prefix}"
        self.lbl_target.configure(text=t)

    def populate_buckets(self):
        for widget in self.shortcuts_frame.winfo_children(): widget.destroy()
        try:
            response = self.s3_manager.client.list_buckets()
            ctk.CTkLabel(self.shortcuts_frame, text="Buckets", font=("Helvetica Neue", 12, "bold")).pack(pady=(5, 10))
            for b in response['Buckets']:
                bname = b['Name']
                cmd = lambda name=bname: self.load_directory(name, "")
                btn = ctk.CTkButton(self.shortcuts_frame, text="🪣 " + bname, fg_color="transparent", 
                                    text_color=("#4B5563", "#9CA3AF"), hover_color=("#D1D5DB", "#374151"), anchor="w", command=cmd)
                btn.pack(fill="x", pady=2)
        except Exception as e:
            print("Error listando buckets:", e)

    def load_directory(self, bucket, prefix):
        self.current_bucket = bucket
        self.current_prefix = prefix
        self.update_breadcrumbs()
        self.update_target_label()
        
        for widget in self.explorer_frame.winfo_children(): widget.destroy()
        
        if not bucket: return

        try:
            # We only need to list CommonPrefixes (Folders) here
            resp = self.s3_manager.client.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter='/')
            
            if 'CommonPrefixes' in resp:
                for cp in resp['CommonPrefixes']:
                    folder_path = cp['Prefix']
                    folder_name = folder_path.rstrip('/').split('/')[-1]
                    cmd = lambda p=folder_path: self.load_directory(bucket, p)
                    
                    card = ctk.CTkFrame(self.explorer_frame, fg_color="transparent")
                    card.pack(fill="x", pady=2, padx=5)
                    btn = ctk.CTkButton(card, text="📂 " + folder_name, fg_color="transparent", hover_color=("#D1D5DB", "#374151"), text_color=("#111827", "#F9FAFB"), font=("Helvetica Neue", 13), anchor="w", command=cmd)
                    btn.pack(fill="x", expand=True)
            else:
                 ctk.CTkLabel(self.explorer_frame, text="No hay subcarpetas.").pack(pady=20)
                 
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def update_breadcrumbs(self):
        for widget in self.breadcrumbs_frame.winfo_children(): widget.destroy()

        if self.current_bucket:
             btn_bucket = ctk.CTkButton(self.breadcrumbs_frame, text=self.current_bucket, fg_color="transparent", text_color=("#C45605", "#E86E12"), hover_color=("#D1D5DB", "#333333"),
                                        command=lambda: self.load_directory(self.current_bucket, ""))
             btn_bucket.pack(side="left", padx=2)

             if self.current_prefix:
                 parts = [p for p in self.current_prefix.split('/') if p]
                 accumulated_path = ""
                 
                 for i, part in enumerate(parts):
                     accumulated_path += part + "/"
                     ctk.CTkLabel(self.breadcrumbs_frame, text=">", text_color=("#6B7280", "gray")).pack(side="left", padx=2)
                     def go_path(p=accumulated_path):
                         self.load_directory(self.current_bucket, p)
                     btn_part = ctk.CTkButton(self.breadcrumbs_frame, text=part, fg_color="transparent", text_color=("#0066CC", "#4DA6FF"), hover_color=("#D1D5DB", "#333333"), command=go_path)
                     btn_part.pack(side="left", padx=2)

    def perform_move(self):
        if not self.current_bucket:
            messagebox.showwarning("Destino nulo", "Seleccione un Bucket destino.", parent=self)
            return

        # Check if moving into the exact same folder
        if self.current_bucket == self.origin_bucket and self.current_prefix == self.origin_prefix:
            messagebox.showinfo("Mover", "El origen y el destino son los mismos.", parent=self)
            return

        # Disable button to prevent double clicks
        self.btn_move.configure(state="disabled", text="Procesando...")
        
        # Fire background movement properly tracked back to Main app
        self.on_close_callback(self.items_to_move, self.current_bucket, self.current_prefix)
        self.destroy()

    def on_close(self):
        self.destroy()
