import customtkinter as ctk
from tkinter import messagebox
import threading
import os

from core.i18n import t
from ui import design
from ui.design import Color, Type, Space, RADIUS, RADIUS_SM

class MoveModal(ctk.CTkToplevel):
    def __init__(self, master, s3_manager, items_to_move, origin_bucket, origin_prefix, on_close_callback):
        super().__init__(master)
        self.title(t("move_modal_title"))
        self.geometry("640x520")
        self.resizable(False, False)
        self.configure(fg_color=Color.BG)
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
        self._load_token = None

        self.init_ui()
        self.populate_buckets()
        
        # Load initially starting at current context if a bucket is selected
        if self.current_bucket:
            self.load_directory(self.current_bucket, self.current_prefix)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def init_ui(self):
        # 1. Top - Breadcrumbs
        self.nav_frame = ctk.CTkFrame(self, height=48, fg_color=Color.SIDEBAR, corner_radius=0)
        self.nav_frame.pack(fill="x", side="top")

        self.breadcrumbs_frame = ctk.CTkFrame(self.nav_frame, fg_color="transparent")
        self.breadcrumbs_frame.pack(side="left", padx=Space.LG, fill="y")

        # 2. Main split: Left Shortcuts, Right Explorer
        self.body_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.body_frame.pack(fill="both", expand=True, padx=Space.LG, pady=Space.LG)

        self.shortcuts_frame = ctk.CTkScrollableFrame(self.body_frame, width=170, fg_color=Color.SIDEBAR,
                                                      corner_radius=RADIUS)
        self.shortcuts_frame.pack(side="left", fill="y", padx=(0, Space.MD))

        self.explorer_frame = ctk.CTkScrollableFrame(self.body_frame, fg_color=Color.SURFACE,
                                                     corner_radius=RADIUS, border_width=1, border_color=Color.LINE)
        self.explorer_frame.pack(side="right", fill="both", expand=True)

        # 3. Bottom - Actions
        self.footer_frame = ctk.CTkFrame(self, height=56, fg_color="transparent")
        self.footer_frame.pack(fill="x", side="bottom", pady=Space.LG, padx=Space.LG)

        self.lbl_target = ctk.CTkLabel(self.footer_frame, text=t("lbl_target_root"), font=Type.LABEL,
                                       text_color=Color.TEXT_MUTED)
        self.lbl_target.pack(side="left")

        self.btn_move = ctk.CTkButton(
            self.footer_frame, text=" " + t("btn_move_here"), image=design.icon("move", 16, Color.ON_ACCENT),
            command=self.perform_move, **design.primary_button_kwargs())
        self.btn_move.pack(side="right")

        self.update_breadcrumbs()

    def update_target_label(self):
        t_text = f"{t('lbl_target_prefix')}{self.current_bucket if self.current_bucket else t('lbl_none')} / {self.current_prefix}"
        self.lbl_target.configure(text=t_text)

    def populate_buckets(self):
        for widget in self.shortcuts_frame.winfo_children():
            widget.destroy()

        ctk.CTkLabel(self.shortcuts_frame, text=t("lbl_buckets").upper(), font=Type.CAPTION,
                     text_color=Color.TEXT_FAINT, anchor="w").pack(fill="x", padx=Space.SM, pady=(Space.SM, Space.SM))

        def fetch():
            try:
                response = self.s3_manager.client.list_buckets()
                buckets = response.get('Buckets', [])
                self.after(0, lambda: self._on_buckets_loaded(buckets))
            except Exception as e:
                print("Error listando buckets:", e)

        threading.Thread(target=fetch, daemon=True).start()

    def _on_buckets_loaded(self, buckets):
        for b in buckets:
            bname = b['Name']
            cmd = lambda name=bname: self.load_directory(name, "")
            btn = ctk.CTkButton(self.shortcuts_frame, text="  " + bname,
                                image=design.icon("bucket", 16, Color.TEXT_MUTED),
                                fg_color="transparent", text_color=Color.TEXT_MUTED,
                                hover_color=Color.CONTROL_HOVER, anchor="w", command=cmd,
                                font=Type.BODY, height=30, corner_radius=RADIUS_SM)
            btn.pack(fill="x", pady=1)
        self._bind_scroll(self.shortcuts_frame, self.shortcuts_frame)

    def load_directory(self, bucket, prefix):
        self.current_bucket = bucket
        self.current_prefix = prefix
        self.update_breadcrumbs()
        self.update_target_label()

        for widget in self.explorer_frame.winfo_children():
            widget.destroy()

        if not bucket:
            return

        lbl_loading = ctk.CTkLabel(self.explorer_frame, text=t("lbl_loading"),
                                   font=Type.BODY, text_color=Color.TEXT_MUTED)
        lbl_loading.pack(pady=Space.XL)

        self._load_token = token = object()

        def fetch():
            subfolders = []
            try:
                paginator = self.s3_manager.client.get_paginator('list_objects_v2')
                for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter='/'):
                    if token is not getattr(self, "_load_token", None):
                        return
                    if 'CommonPrefixes' in page:
                        for cp in page['CommonPrefixes']:
                            folder_path = cp['Prefix']
                            folder_name = folder_path.rstrip('/').split('/')[-1]
                            subfolders.append((folder_path, folder_name))
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror(t("lbl_error"), str(err), parent=self))
                return

            if token is not getattr(self, "_load_token", None):
                return
            self.after(0, lambda: self._on_directory_loaded(token, bucket, subfolders))

        threading.Thread(target=fetch, daemon=True).start()

    def _on_directory_loaded(self, token, bucket, subfolders):
        if token is not getattr(self, "_load_token", None):
            return
        for widget in self.explorer_frame.winfo_children():
            widget.destroy()

        if subfolders:
            subfolders.sort(key=lambda x: x[1].lower())
            for folder_path, folder_name in subfolders:
                cmd = lambda p=folder_path: self.load_directory(bucket, p)
                card = ctk.CTkFrame(self.explorer_frame, fg_color="transparent")
                card.pack(fill="x", pady=1, padx=Space.XS)
                btn = ctk.CTkButton(card, text="  " + folder_name,
                                    image=design.icon("folder", 18, Color.TEXT),
                                    fg_color="transparent", hover_color=Color.CONTROL_HOVER,
                                    text_color=Color.TEXT, font=Type.BODY, anchor="w",
                                    height=34, corner_radius=RADIUS_SM, command=cmd)
                btn.pack(fill="x", expand=True)
        else:
            ctk.CTkLabel(self.explorer_frame, text=t("lbl_no_subfolders"), font=Type.BODY,
                         text_color=Color.TEXT_FAINT).pack(pady=Space.XL)

        self._bind_scroll(self.explorer_frame, self.explorer_frame)

    def _bind_scroll(self, subtree, scroll_frame):
        canvas = scroll_frame._parent_canvas
        try:
            canvas.configure(xscrollincrement=1, yscrollincrement=1)
            scroll_frame._mouse_wheel_all = lambda event: "break"
        except Exception:
            pass

        def on_wheel(event):
            if event.num == 4:
                step = -36
            elif event.num == 5:
                step = 36
            elif abs(getattr(event, "delta", 0)) >= 120:
                step = -int(event.delta / 120) * 36
            else:
                delta = getattr(event, "delta", 0) or 0
                step = -int(delta * 32) if delta else 0
            if canvas.yview() != (0.0, 1.0) and step:
                canvas.yview_scroll(step, "units")
            return "break"

        def on_touchpad(event):
            raw = int(getattr(event, "delta", 0) or 0)
            dy = raw & 0xFFFF
            if dy >= 0x8000:
                dy -= 0x10000
            if dy == 0:
                return "break"
            step = -int(dy * 1.5)
            if canvas.yview() != (0.0, 1.0) and step:
                canvas.yview_scroll(step, "units")
            return "break"

        def apply(w):
            w.bind("<MouseWheel>", on_wheel, add="+")
            w.bind("<Button-4>", on_wheel, add="+")
            w.bind("<Button-5>", on_wheel, add="+")
            try:
                w.bind("<TouchpadScroll>", on_touchpad, add="+")
            except Exception:
                pass
            for child in w.winfo_children():
                apply(child)

        apply(subtree)

    def update_breadcrumbs(self):
        for widget in self.breadcrumbs_frame.winfo_children(): widget.destroy()

        def crumb(text, active, command):
            return ctk.CTkButton(
                self.breadcrumbs_frame, text=text, width=0, height=30,
                font=Type.HEADING if active else Type.BODY, corner_radius=RADIUS_SM,
                fg_color="transparent", hover=not active, hover_color=Color.CONTROL_HOVER,
                text_color=Color.TEXT if active else Color.TEXT_MUTED,
                command=(None if active else command))

        def sep():
            ctk.CTkLabel(self.breadcrumbs_frame, text="/", font=Type.BODY,
                         text_color=Color.LINE_STRONG).pack(side="left", padx=Space.XS)

        if self.current_bucket:
             bucket_active = not self.current_prefix
             crumb(self.current_bucket, bucket_active,
                   lambda: self.load_directory(self.current_bucket, "")).pack(side="left")

             if self.current_prefix:
                 parts = [p for p in self.current_prefix.split('/') if p]
                 accumulated_path = ""
                 for i, part in enumerate(parts):
                     accumulated_path += part + "/"
                     sep()
                     is_last = (i == len(parts) - 1)
                     def go_path(p=accumulated_path):
                         self.load_directory(self.current_bucket, p)
                     crumb(part, is_last, go_path).pack(side="left")

    def perform_move(self):
        if not self.current_bucket:
            messagebox.showwarning(t("msg_null_target_title"), t("msg_select_target_bucket"), parent=self)
            return

        # Check if moving into the exact same folder
        if self.current_bucket == self.origin_bucket and self.current_prefix == self.origin_prefix:
            messagebox.showinfo(t("msg_move_title"), t("msg_same_origin_dest"), parent=self)
            return

        # Disable button to prevent double clicks
        self.btn_move.configure(state="disabled", text=t("btn_processing"))
        
        # Fire background movement properly tracked back to Main app
        self.on_close_callback(self.items_to_move, self.current_bucket, self.current_prefix)
        self.destroy()

    def on_close(self):
        self.destroy()
