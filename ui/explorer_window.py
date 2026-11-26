import customtkinter as ctk
import os
import sys
import json
import threading
import concurrent.futures
import csv
import queue
import time
import mimetypes
from datetime import datetime, timedelta
import keyring
from PIL import Image, ImageTk
from tkinter import filedialog, messagebox, simpledialog
from tkinterdnd2 import TkinterDnD, DND_FILES

from core.auth_manager import AuthManager
from core.s3_manager import S3Manager, DEFAULT_TRANSFER_CONFIG
from core import secure_store
from ui.login_window import LoginWindow
from ui.move_modal import MoveModal
from utils.helpers import resource_path, get_download_dir
from core.i18n import t, init_i18n, get_lang
from ui import design
from ui.design import Color, Type, Space, RADIUS, RADIUS_SM

class PromptDialog(ctk.CTkInputDialog):
    """CTkInputDialog with support for prefilled initial value."""
    def __init__(self, initial_value="", *args, **kwargs):
        self._initial_value = initial_value
        super().__init__(*args, **kwargs)

    def _create_widgets(self):
        super()._create_widgets()
        if self._initial_value:
            self._entry.insert(0, str(self._initial_value))
            self._entry.select_range(0, "end")

class S3UniversalApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        self.title(t("app_title"))
        self.geometry("1400x900")
        self.withdraw()
        
        # Load Icon (Local version)
        self.load_app_icon()

        # Cross-platform config path
        # Replaced old configurations with AuthManager
        self.auth_manager = AuthManager()
        self.s3_manager = None

        self.current_bucket = None
        self.current_prefix = "" 
        # UI State persistent path
        self.config_path = os.path.join(os.path.expanduser("~"), ".s3_commander_config.json")
        
        self.should_restart = False
        self.view_mode = "grid"
        self.sort_mode = "recent"   # "recent" | "name"
        self._load_token = None
        self._current_items = None
        self._loading_lbl = None
        self._count_hint = None
        self._file_sizes = {}  # full_path -> size_in_bytes cache for instant bulk stats
        self.thumbnail_cache = []
        self.cloudfront_url = ""
        
        self.load_session()
        self.init_ui()
        self._install_global_wheel()

        # Multiple selection
        self.selected_items = set() # Stores tuple: (full_path, type, name)
        self.after(100, self.check_login_status)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _install_global_wheel(self):
        """Robust, pixel-smooth wheel & trackpad scrolling for macOS Aqua on Tk 9.

        Configures 1-pixel increments on scrollable canvases so motion is continuous
        and fluid rather than stepped in 8px chunks. Emits native deltas on every
        touchpad event so there are zero dropped frames, no stuttering, and natural
        macOS momentum scrolling.
        """
        self._touch_accum = 0.0

        def scroll_canvases():
            # (canvas, content_frame) pairs for each scroll region.
            pairs = []
            for attr in ("file_list_frame", "sidebar_buckets_frame"):
                f = getattr(self, attr, None)
                if f is not None:
                    try:
                        f._parent_canvas.configure(xscrollincrement=1, yscrollincrement=1)
                        f._mouse_wheel_all = lambda event: "break"
                    except Exception:
                        pass
                    pairs.append((f._parent_canvas, f))
            return pairs

        def belongs(widget, canvas, frame):
            # Match widget or any ancestor against canvas and content frame
            w = widget
            while w is not None:
                if w is canvas or w is frame:
                    return True
                w = getattr(w, "master", None)
            return False

        def target_canvas(event=None):
            under = None
            try:
                under = self.winfo_containing(self.winfo_pointerx(), self.winfo_pointery())
            except Exception:
                under = None
            if under is None and event is not None:
                under = getattr(event, "widget", None)
            if under is None:
                return None
            for canvas, frame in scroll_canvases():
                if belongs(under, canvas, frame):
                    return canvas
            return None

        def do_scroll(step, event=None):
            canvas = target_canvas(event)
            if canvas is None or not step:
                return
            if canvas.yview() != (0.0, 1.0):
                canvas.yview_scroll(step, "units")

        def on_wheel(event):
            do_scroll(self._wheel_delta(event), event)
            return "break"

        def on_touchpad(event):
            # Tk 9 / Aqua reports vertical trackpad delta in the LOW 16 bits of %D.
            raw = int(getattr(event, "delta", 0) or 0)
            dy = raw & 0xFFFF
            if dy >= 0x8000:
                dy -= 0x10000
            if dy == 0:
                return "break"
            # Natural trackpad sensitivity (1.5x gives responsive, buttery-smooth 1:1 motion)
            pixels = dy * 1.5
            self._touch_accum += pixels
            step = int(self._touch_accum)
            if step != 0:
                self._touch_accum -= step
                do_scroll(-step, event)
            return "break"

        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(ev, on_wheel, add="+")
        try:
            self.bind_all("<TouchpadScroll>", on_touchpad, add="+")
        except Exception:
            pass  # older Tk without TouchpadScroll; wheel bindings still apply

    def on_close(self):
        import os
        os._exit(0)

    # --- NEW ICON LOADING VERSION ---
    def load_app_icon(self):
        try:
            # Look for "s3icono.png" attached during compilation
            icon_path = resource_path("s3icono.png")
            
            if os.path.exists(icon_path):
                image = Image.open(icon_path)
                self.icon_image = ImageTk.PhotoImage(image)
                # Set window and Dock icon at runtime
                self.iconphoto(True, self.icon_image)
            else:
                print(f"{t('warn_no_icon')}{icon_path}")
        except Exception as e:
            print(f"{t('err_loading_icon')}{e}")

    def init_ui(self):
        self.configure(fg_color=Color.BG)

        # ================= Sidebar =================
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=Color.SIDEBAR)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Brand / title block
        header = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        header.pack(fill="x", padx=Space.XL, pady=(Space.XL, Space.LG))
        ctk.CTkLabel(header, text="s3", font=design.font(24, "bold"),
                     text_color=Color.ACCENT).pack(side="left")
        ctk.CTkLabel(header, text="Uploader", font=design.Type.DISPLAY,
                     text_color=Color.TEXT).pack(side="left", padx=(2, 0))

        ctk.CTkLabel(self.sidebar, text=t("lbl_my_repos").upper(), font=Type.CAPTION,
                     text_color=Color.TEXT_FAINT, anchor="w").pack(fill="x", padx=Space.XL, pady=(0, Space.SM))
        self.sidebar_buckets_frame = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.sidebar_buckets_frame.pack(fill="both", expand=True, padx=Space.MD, pady=0)

        self.btn_refresh_buckets = ctk.CTkButton(
            self.sidebar, text=" " + t("btn_refresh"), image=design.icon("refresh", 16),
            anchor="w", command=self.populate_sidebar_buckets, **design.ghost_button_kwargs())
        self.btn_refresh_buckets.pack(pady=(Space.SM, Space.XS), padx=Space.MD, fill="x")

        self._divider(self.sidebar).pack(fill="x", padx=Space.XL, pady=Space.MD)

        # Settings cluster
        self.btn_change_pass = ctk.CTkButton(
            self.sidebar, text=" " + t("btn_change_pin"), image=design.icon("key", 16),
            anchor="w", command=self.change_password_task, **design.ghost_button_kwargs())
        self.btn_change_pass.pack(pady=Space.XS, padx=Space.MD, fill="x")

        self.btn_cloudfront = ctk.CTkButton(
            self.sidebar, text=" CloudFront URL", image=design.icon("cloud", 16),
            anchor="w", command=self.set_cloudfront_url, **design.ghost_button_kwargs())
        self.btn_cloudfront.pack(pady=Space.XS, padx=Space.MD, fill="x")

        # Bottom cluster (packed bottom-up)
        self.btn_logout = ctk.CTkButton(
            self.sidebar, text=" " + t("btn_logout"), image=design.icon("logout", 16, Color.DANGER),
            anchor="w", command=self.logout, **design.ghost_button_kwargs())
        self.btn_logout.configure(text_color=Color.DANGER)
        self.btn_logout.pack(side="bottom", pady=(Space.XS, Space.LG), padx=Space.MD, fill="x")

        self.lang_var = ctk.StringVar(value=get_lang())
        self.lang_menu = ctk.CTkSegmentedButton(
            self.sidebar, values=["es", "en"], variable=self.lang_var, command=self.change_language,
            font=Type.LABEL, selected_color=Color.ACCENT, selected_hover_color=Color.ACCENT_HOVER,
            unselected_color=Color.SUBTLE, unselected_hover_color=Color.CONTROL_HOVER,
            fg_color=Color.SUBTLE, corner_radius=RADIUS_SM)
        self.lang_menu.pack(side="bottom", pady=(0, Space.SM), padx=Space.XL, fill="x")
        ctk.CTkLabel(self.sidebar, text=t("lbl_language").upper(), font=Type.CAPTION,
                     text_color=Color.TEXT_FAINT, anchor="w").pack(side="bottom", padx=Space.XL, fill="x")

        self.theme_switch = ctk.CTkSwitch(
            self.sidebar, text=t("sw_light_mode") if ctk.get_appearance_mode() == "Dark" else t("sw_dark_mode"),
            font=Type.LABEL, progress_color=Color.ACCENT, command=self.toggle_theme)
        if ctk.get_appearance_mode() == "Light":
            self.theme_switch.select()
        self.theme_switch.pack(side="bottom", anchor="w", pady=Space.MD, padx=Space.XL)

        self.storage_menu = ctk.CTkOptionMenu(
            self.sidebar, values=["STANDARD", "GLACIER_IR", "DEEP_ARCHIVE", "ONEZONE_IA"], font=Type.LABEL,
            fg_color=Color.SUBTLE, button_color=Color.SUBTLE, button_hover_color=Color.CONTROL_HOVER,
            text_color=Color.TEXT, corner_radius=RADIUS_SM, dropdown_font=Type.LABEL)
        self.storage_menu.pack(side="bottom", pady=(0, Space.MD), padx=Space.XL, fill="x")
        ctk.CTkLabel(self.sidebar, text=t("lbl_storage_class").upper(), font=Type.CAPTION,
                     text_color=Color.TEXT_FAINT, anchor="w").pack(side="bottom", padx=Space.XL, fill="x", pady=(Space.LG, Space.XS))

        # ================= Main View =================
        self.main_view = ctk.CTkFrame(self, fg_color=Color.BG, corner_radius=0)
        self.main_view.pack(side="right", fill="both", expand=True)

        # --- Top navigation bar (back + breadcrumbs) ---
        self.nav_frame = ctk.CTkFrame(self.main_view, fg_color="transparent", height=56)
        self.nav_frame.pack(fill="x", padx=Space.XL, pady=(Space.LG, Space.SM))

        self.btn_back = ctk.CTkButton(
            self.nav_frame, text="", image=design.icon("back", 18), width=36, height=36,
            command=self.go_back, fg_color="transparent", hover_color=Color.CONTROL_HOVER,
            corner_radius=RADIUS_SM)
        self.btn_back.pack(side="left", padx=(0, Space.SM))

        self.path_scroll = ctk.CTkScrollableFrame(self.nav_frame, height=36, orientation="horizontal", fg_color="transparent")
        self.path_scroll.pack(side="left", fill="x", expand=True)
        self.breadcrumbs_frame = ctk.CTkFrame(self.path_scroll, fg_color="transparent")
        self.breadcrumbs_frame.pack(side="left", fill="y")

        self._divider(self.main_view).pack(fill="x", padx=Space.XL)

        # --- Object / bucket list ---
        self.file_list_frame = ctk.CTkScrollableFrame(self.main_view, fg_color="transparent")
        self.file_list_frame.pack(fill="both", expand=True, padx=Space.LG, pady=Space.MD)

        self.columns_per_row = 5
        for i in range(self.columns_per_row):
            self.file_list_frame.grid_columnconfigure(i, weight=1)

        # Bind wheel scrolling on the list container and its canvas up front,
        # so the empty area scrolls even before/without items, and keep the
        # CustomTkinter global handler from stealing the gesture.
        self._bind_scroll(self.file_list_frame, self.file_list_frame)

        self._divider(self.main_view).pack(fill="x", padx=Space.XL)

        # --- Action toolbar ---
        self.actions_frame = ctk.CTkFrame(self.main_view, fg_color="transparent")
        self.actions_frame.pack(fill="x", padx=Space.XL, pady=Space.MD)

        self.btn_up_files = ctk.CTkButton(
            self.actions_frame, text=" " + t("btn_up_files"), image=design.icon("upload", 16, Color.ON_ACCENT),
            command=lambda: self.upload_task("files"), **design.primary_button_kwargs())
        self.btn_up_files.pack(side="left", padx=(0, Space.SM))

        self.btn_up_folder = ctk.CTkButton(
            self.actions_frame, text=" " + t("btn_up_folder"), image=design.icon("upload", 16),
            command=lambda: self.upload_task("folder"), **design.secondary_button_kwargs())
        self.btn_up_folder.pack(side="left", padx=Space.XS)

        self.btn_new_folder = ctk.CTkButton(
            self.actions_frame, text=" " + t("btn_new_folder"), image=design.icon("folder_plus", 16),
            command=self.create_folder_task, **design.secondary_button_kwargs())
        self.btn_new_folder.pack(side="left", padx=Space.XS)

        # Separator between create and selection actions
        self._vdivider(self.actions_frame).pack(side="left", padx=Space.MD, pady=Space.SM)

        # Selection actions are icon-only to keep the toolbar within the window
        # width; tooltips keep them discoverable.
        def _sel_btn(icon_name, cmd, danger=False):
            kw = dict(width=38, height=36, text="",
                      fg_color="transparent", hover_color=Color.CONTROL_HOVER,
                      border_width=1, border_color=Color.LINE_STRONG,
                      corner_radius=RADIUS, command=cmd)
            col = Color.DANGER if danger else Color.TEXT
            return ctk.CTkButton(self.actions_frame, image=design.icon(icon_name, 18, col), **kw)

        self.btn_download_sel = _sel_btn("download", self.download_selected_items)
        self.btn_download_sel.pack(side="left", padx=Space.XS)
        self._add_tooltip(self.btn_download_sel, t("btn_download_sel"))

        self.btn_move_sel = _sel_btn("move", self.move_selected_items)
        self.btn_move_sel.pack(side="left", padx=Space.XS)
        self._add_tooltip(self.btn_move_sel, t("btn_move_sel"))

        self.btn_links_sel = _sel_btn("link", self.copy_selected_links)
        self.btn_links_sel.pack(side="left", padx=Space.XS)
        self._add_tooltip(self.btn_links_sel, t("btn_links_sel"))

        self.btn_delete_sel = _sel_btn("trash", self.delete_selected_items, danger=True)
        self.btn_delete_sel.pack(side="left", padx=Space.XS)
        self._add_tooltip(self.btn_delete_sel, t("btn_delete_sel"))

        self.btn_view_mode = ctk.CTkButton(
            self.actions_frame, text="", width=36, height=36,
            image=design.icon("list" if self.view_mode == "grid" else "grid", 18),
            fg_color="transparent", hover_color=Color.CONTROL_HOVER, corner_radius=RADIUS_SM,
            command=self.toggle_view_mode)
        self.btn_view_mode.pack(side="right")

        self.btn_sort_mode = ctk.CTkButton(
            self.actions_frame, width=0, height=36,
            text=" " + (t("sort_recent") if self.sort_mode == "recent" else t("sort_name")),
            image=design.icon("sort", 16),
            fg_color="transparent", hover_color=Color.CONTROL_HOVER, corner_radius=RADIUS_SM,
            text_color=Color.TEXT_MUTED, font=Type.LABEL, command=self.toggle_sort_mode)
        self.btn_sort_mode.pack(side="right", padx=Space.SM)

        # --- Progress (hidden until an operation runs) ---
        self.progress_frame = ctk.CTkFrame(self.main_view, fg_color="transparent")
        self.prog_label = ctk.CTkLabel(self.progress_frame, text=t("lbl_ready"), font=Type.CAPTION,
                                       text_color=Color.TEXT_MUTED, anchor="w")
        self.prog_label.pack(fill="x", padx=Space.XL, pady=(0, Space.XS))
        self.prog_bar = ctk.CTkProgressBar(self.progress_frame, progress_color=Color.ACCENT,
                                           fg_color=Color.LINE, height=4, corner_radius=2)
        self.prog_bar.pack(fill="x", padx=Space.XL, pady=(0, Space.MD))
        self.prog_bar.set(0)
        self._progress_visible = False

        # Enable File Drop
        self.drop_target_register(DND_FILES)
        self.dnd_bind('<<Drop>>', self.on_drop)

    # -- Small layout helpers --------------------------------------------
    def _add_tooltip(self, widget, text):
        """Lightweight hover tooltip so icon-only buttons stay discoverable."""
        state = {"tip": None, "after": None}

        def show():
            if state["tip"] or not text:
                return
            try:
                x = widget.winfo_rootx() + 10
                y = widget.winfo_rooty() + widget.winfo_height() + 6
            except Exception:
                return
            tip = ctk.CTkToplevel(self)
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)
            tip.geometry(f"+{x}+{y}")
            ctk.CTkLabel(tip, text=text, font=Type.CAPTION, fg_color=Color.SUBTLE,
                         text_color=Color.TEXT, corner_radius=RADIUS_SM,
                         padx=Space.SM, pady=Space.XS).pack()
            state["tip"] = tip

        def on_enter(_e):
            state["after"] = widget.after(450, show)

        def on_leave(_e):
            if state["after"]:
                widget.after_cancel(state["after"]); state["after"] = None
            if state["tip"]:
                state["tip"].destroy(); state["tip"] = None

        widget.bind("<Enter>", on_enter, add="+")
        widget.bind("<Leave>", on_leave, add="+")

    def _divider(self, parent):
        return ctk.CTkFrame(parent, height=1, fg_color=Color.LINE, corner_radius=0)

    def _vdivider(self, parent):
        return ctk.CTkFrame(parent, width=1, height=22, fg_color=Color.LINE, corner_radius=0)

    def show_progress(self, show=True):
        if show and not self._progress_visible:
            self.progress_frame.pack(fill="x", before=self.actions_frame)
            self._progress_visible = True
        elif not show and self._progress_visible:
            self.progress_frame.pack_forget()
            self._progress_visible = False

    def _wheel_delta(self, event):
        """Normalize a mouse-wheel event into pixel scroll units across platforms."""
        num = getattr(event, "num", None)
        if num == 4:
            return -36
        if num == 5:
            return 36
        delta = getattr(event, "delta", 0) or 0
        if delta == 0:
            return 0
        if abs(delta) >= 120:                 # Windows wheel notch
            return -int(delta / 120) * 36
        # macOS wheel notch (delta is typically +/- 1..5)
        return -int(delta * 32)

    def _bind_scroll(self, subtree, scroll_frame):
        """Configure 1-pixel resolution and prevent CTk conflicts."""
        try:
            scroll_frame._parent_canvas.configure(xscrollincrement=1, yscrollincrement=1)
            scroll_frame._mouse_wheel_all = lambda event: "break"
        except Exception:
            pass

    def _bind_list_scroll(self, widget):
        pass

    def make_progress_tracker(self, total_bytes, label_prefix):
        """Build a boto3 Callback that updates the progress UI without flooding it.

        boto3 invokes the callback once per transferred chunk (thousands of
        times per second for a large file). Marshalling every one of those onto
        the Tk event loop with self.after() is what made transfers stutter and
        the whole app feel sluggish. This tracker coalesces updates: it only
        schedules a UI refresh when at least ~100 ms have passed since the last
        one (or when the transfer finishes), so the event loop stays responsive.
        """
        app = self
        mb_total = round(total_bytes / (1024 * 1024), 2)

        class _Tracker:
            def __init__(self):
                self._seen = 0
                self._lock = threading.Lock()
                self._last_emit = 0.0
                self._pending = False
                self._file_idx = 0
                self._total_files = 0
                self._current_file = ""

            def set_file_context(self, idx, total, filename):
                with self._lock:
                    self._file_idx = idx
                    self._total_files = total
                    self._current_file = filename
                    seen = self._seen
                pct = (seen / total_bytes) if total_bytes > 0 else 1.0
                app.after(0, lambda: self._emit(pct, seen))

            def add_bytes(self, amount):
                with self._lock:
                    self._seen += amount
                    seen = self._seen
                pct = (seen / total_bytes) if total_bytes > 0 else 1.0
                app.after(0, lambda: self._emit(pct, seen))

            def _emit(self, pct, seen):
                self._pending = False
                app.prog_bar.set(pct)
                mb_seen = round(seen / (1024 * 1024), 2)
                with self._lock:
                    info = ""
                    if self._total_files > 1:
                        info = f"[{self._file_idx}/{self._total_files}] {self._current_file} • "
                    elif self._current_file:
                        info = f"{self._current_file} • "
                app.prog_label.configure(
                    text=f"{label_prefix}: {info}{int(pct * 100)}% ({mb_seen} MB / {mb_total} MB)")

            def __call__(self, bytes_amount):
                with self._lock:
                    self._seen += bytes_amount
                    seen = self._seen
                pct = (seen / total_bytes) if total_bytes > 0 else 1.0
                now = time.monotonic()
                done = seen >= total_bytes
                if done or (now - self._last_emit) >= 0.1:
                    if not self._pending or done:
                        self._last_emit = now
                        self._pending = True
                        app.after(0, lambda: self._emit(pct, seen))

        return _Tracker()

    def on_drop(self, event):
        data = event.data
        paths = self.parse_dropped_files(data)
        if not paths: return
        self.handle_upload_drop(paths)

    def parse_dropped_files(self, data):
        # tkinterdnd2 hands the dropped paths as a Tcl list. When several files
        # are dropped, macOS/Tk mixes braced (paths with spaces) and unbraced
        # tokens, e.g. "{/a b/one.txt} /plain/two.txt {/c d/three.txt}". The old
        # brace-only regex dropped the unbraced ones and mis-parsed the whole
        # string when the last path had no braces, so multi-file drops uploaded
        # nothing. Tk's own list splitter handles every case correctly.
        if not data:
            return []
        try:
            paths = list(self.tk.splitlist(data))
        except Exception:
            # Fallback: strip a single pair of wrapping braces if present.
            s = data.strip()
            paths = [s[1:-1] if s.startswith('{') and s.endswith('}') else s]
        return [p for p in (pth.strip() for pth in paths) if p]

    def handle_upload_drop(self, paths):
        if not self.s3_manager or not self.current_bucket:
            messagebox.showwarning(t("msg_attention_title"), t("msg_connect_select_bucket"))
            return

        if messagebox.askyesno(t("msg_confirm_upload_title"), f"{t('msg_confirm_upload_text_1')}{len(paths)}{t('msg_confirm_upload_text_2')}"):
            threading.Thread(target=self.hilo_upload, args=(paths, "mixed"), daemon=True).start()

    def save_session(self):
        config = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    config = json.load(f)
            except: pass
        config["last_bucket"] = self.current_bucket
        config["last_prefix"] = self.current_prefix
        config["view_mode"] = getattr(self, "view_mode", "grid")
        config["sort_mode"] = getattr(self, "sort_mode", "recent")
        config["language"] = getattr(self, "next_lang", get_lang())
        config["appearance_mode"] = ctk.get_appearance_mode().lower()
        # Sensitive values live in the OS keychain, never in this JSON file.
        config.pop("delete_password", None)
        config.pop("cloudfront_url", None)
        with open(self.config_path, "w") as f:
            json.dump(config, f)

    def load_session(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    c = json.load(f)
                    self.current_bucket = c.get("last_bucket")
                    self.current_prefix = c.get("last_prefix", "")
                    self.view_mode = c.get("view_mode", "grid")
                    self.sort_mode = c.get("sort_mode", "recent")
                    self._migrate_secrets_to_keychain(c)
            except: pass
        self.cloudfront_url = secure_store.get_cloudfront_url()

    def _migrate_secrets_to_keychain(self, c):
        """Move values older versions kept in plain JSON into the keychain."""
        legacy_pin = c.get("delete_password")
        legacy_cf = c.get("cloudfront_url")
        if legacy_pin is None and legacy_cf is None:
            return
        # Legacy PINs were stored in plain text (and often left at a public
        # default), so they are discarded; the user creates a new one on demand.
        if legacy_cf and not secure_store.get_cloudfront_url():
            secure_store.set_cloudfront_url(legacy_cf)
        c.pop("delete_password", None)
        c.pop("cloudfront_url", None)
        try:
            with open(self.config_path, "w") as f:
                json.dump(c, f)
        except Exception:
            pass

    def _create_delete_pin(self):
        """Ask the user to define a delete PIN. Returns True if one was saved."""
        pin = ctk.CTkInputDialog(text=t("msg_create_pin"), title=t("msg_new_pin_title")).get_input()
        if not pin:
            return False
        confirm = ctk.CTkInputDialog(text=t("msg_confirm_pin"), title=t("msg_new_pin_title")).get_input()
        if confirm != pin:
            messagebox.showerror(t("lbl_error"), t("msg_pin_mismatch"))
            return False
        if not secure_store.set_delete_pin(pin):
            messagebox.showerror(t("lbl_error"), t("msg_keychain_error"))
            return False
        messagebox.showinfo(t("msg_success_title"), t("msg_pin_updated"))
        return True

    def _check_delete_pin(self, prompt):
        """True if the PIN is correct, False if wrong, None if cancelled."""
        if not secure_store.has_delete_pin() and not self._create_delete_pin():
            return None
        pwd = ctk.CTkInputDialog(text=prompt, title=t("msg_security_title")).get_input()
        if pwd is None:
            return None
        if secure_store.verify_delete_pin(pwd):
            return True
        messagebox.showerror(t("msg_security_title"), t("msg_incorrect_pass"))
        return False



    def check_login_status(self):
        result = self.auth_manager.load_session()
        if result:
            ak, sk, rg = result
            self.on_login_success(ak, sk, rg)
        else:
            LoginWindow(self, self.on_login_success)

    def on_login_success(self, ak, sk, rg):
        self.deiconify()
        self.auth_manager.save_session(ak, sk, rg)
        
        try:
            self.s3_manager = S3Manager(ak, sk, rg)
            self.populate_sidebar_buckets()
            if self.current_bucket:
                self.enter_bucket(self.current_bucket)
            else:
                self.list_buckets()
        except Exception as e:
            print("ERROR FATAL en on_login_success: ", str(e))
            import traceback
            traceback.print_exc()
            messagebox.showerror("Error de Conexión", f"Error: {e}")
            LoginWindow(self, self.on_login_success)

    def populate_sidebar_buckets(self):
        for widget in self.sidebar_buckets_frame.winfo_children():
            widget.destroy()
        if not self.s3_manager: return
        try:
            response = self.s3_manager.client.list_buckets()
            for b in response['Buckets']:
                bname = b['Name']
                cmd = lambda name=bname: self.enter_bucket_from_sidebar(name)
                is_active = (bname == self.current_bucket)
                btn = ctk.CTkButton(
                    self.sidebar_buckets_frame, text="  " + bname,
                    image=design.icon("bucket", 16, Color.ACCENT if is_active else Color.TEXT_MUTED),
                    anchor="w", command=cmd, font=Type.BODY, corner_radius=RADIUS_SM, height=32,
                    fg_color=Color.SUBTLE if is_active else "transparent",
                    hover_color=Color.CONTROL_HOVER,
                    text_color=Color.TEXT if is_active else Color.TEXT_MUTED)
                btn.pack(fill="x", pady=1)
            self._bind_scroll(self.sidebar_buckets_frame, self.sidebar_buckets_frame)
        except Exception as e:
            print("Error listando buckets:", e)

    def enter_bucket_from_sidebar(self, bucket_name):
        self.current_prefix = ""
        self.enter_bucket(bucket_name)

    def update_breadcrumbs(self):
        # Clear previous breadcrumbs
        for widget in self.breadcrumbs_frame.winfo_children():
            widget.destroy()

        def crumb(text, active, command, image=None):
            return ctk.CTkButton(
                self.breadcrumbs_frame, text=text, image=image, width=0, height=30,
                font=Type.HEADING if active else Type.BODY, corner_radius=RADIUS_SM,
                fg_color="transparent", hover=not active,
                hover_color=Color.CONTROL_HOVER,
                text_color=Color.TEXT if active else Color.TEXT_MUTED,
                command=(None if active else command))

        def sep():
            ctk.CTkLabel(self.breadcrumbs_frame, text="/", font=Type.BODY,
                         text_color=Color.LINE_STRONG).pack(side="left", padx=Space.XS)

        # Home (buckets list)
        is_home = not self.current_bucket
        crumb("", is_home, self.list_buckets, image=design.icon("home", 18, Color.TEXT if is_home else Color.TEXT_MUTED)).pack(side="left")

        if self.current_bucket:
            sep()
            bucket_active = not self.current_prefix

            def go_bucket_root(b=self.current_bucket):
                self.current_prefix = ""
                self.enter_bucket(b)

            crumb(self.current_bucket, bucket_active, go_bucket_root).pack(side="left")

            if self.current_prefix:
                parts = [p for p in self.current_prefix.split('/') if p]
                accumulated_path = ""
                for i, part in enumerate(parts):
                    accumulated_path += part + "/"
                    sep()
                    is_last = (i == len(parts) - 1)

                    def go_path(p=accumulated_path):
                        self.current_prefix = p
                        self.enter_bucket(self.current_bucket)

                    crumb(part, is_last, go_path).pack(side="left")

    def toggle_selection(self, item_type, name, full_path):
        item = (full_path, item_type, name)
        if item in self.selected_items:
            self.selected_items.remove(item)
        else:
            self.selected_items.add(item)

    def clear_list_frame(self):
        self.grid_idx = 0  # Reset counter
        self.selected_items.clear() # Clear selection when changing view/bucket
        self._file_sizes.clear()
        self.thumbnail_cache.clear()
        # Drop references to transient overlays before destroying children, so
        # we never point at a destroyed widget.
        self._loading_lbl = None
        self._clear_count_hint()
        for widget in self.file_list_frame.winfo_children():
            widget.destroy()

    def toggle_view_mode(self):
        if self.view_mode == "grid":
            self.view_mode = "list"
            self.btn_view_mode.configure(image=design.icon("grid", 18))
        else:
            self.view_mode = "grid"
            self.btn_view_mode.configure(image=design.icon("list", 18))
        self._rerender_current_view()

    def toggle_sort_mode(self):
        self.sort_mode = "name" if self.sort_mode == "recent" else "recent"
        self.btn_sort_mode.configure(
            text=" " + (t("sort_recent") if self.sort_mode == "recent" else t("sort_name")))
        self.save_session()
        self._rerender_current_view()

    def logout(self):
        self.auth_manager.clear_session()
        self.current_bucket = None
        self.s3_manager = None
        for widget in getattr(self, 'sidebar_buckets_frame', ctk.CTkFrame(self)).winfo_children(): widget.destroy()
        for widget in getattr(self, 'file_list_frame', ctk.CTkFrame(self)).winfo_children(): widget.destroy()
        self.withdraw()
        LoginWindow(self, self.on_login_success)

    def change_password_task(self):
        if not secure_store.has_delete_pin():
            self._create_delete_pin()
            return
        curr_pwd = ctk.CTkInputDialog(text=t("msg_enter_current_pin"), title=t("msg_security_title")).get_input()
        if curr_pwd is None:
            return
        if secure_store.verify_delete_pin(curr_pwd):
            self._create_delete_pin()
        else:
            messagebox.showerror(t("lbl_error"), t("msg_incorrect_pin"))

    def set_cloudfront_url(self):
        current = getattr(self, "cloudfront_url", "")
        hint = f"URL actual: {current}\n\nIngresa la URL base de CloudFront (ej: https://xxxxxxxxxxxxxx.cloudfront.net)\nDeja vacío para usar URLs presignadas de S3."
        new_url = ctk.CTkInputDialog(text=hint, title="Configurar CloudFront").get_input()
        if new_url is not None:
            self.cloudfront_url = new_url.strip().rstrip("/")
            if not secure_store.set_cloudfront_url(self.cloudfront_url):
                messagebox.showerror(t("lbl_error"), t("msg_keychain_error"))
                return
            if self.cloudfront_url:
                messagebox.showinfo("CloudFront", f"URL configurada:\n{self.cloudfront_url}")
            else:
                messagebox.showinfo("CloudFront", "CloudFront desactivado. Se usarán URLs presignadas de S3.")

    def change_language(self, new_lang):
        try:
            self.next_lang = new_lang
            self.save_session()
            
            # Switch strings dynamically
            from core.i18n import init_i18n, t
            init_i18n(new_lang)
            self.title(t("app_title"))

            # Destroy all active components except top-level windows
            for widget in self.winfo_children():
                if not isinstance(widget, ctk.CTkToplevel):
                    widget.destroy()

            # Natively rebuild the interface strings
            self.init_ui()

            # Refresh buckets data without reloading session
            if self.s3_manager:
                self.list_buckets()
                if self.current_bucket:
                    self.enter_bucket(self.current_bucket)

        except Exception as e:
            import traceback
            traceback.print_exc()

    def list_buckets(self):
        self.current_bucket = None
        self._current_items = None  # invalidate cache
        self.update_breadcrumbs()
        self.clear_list_frame()
        self.populate_sidebar_buckets()
        
        self._load_token = object()  # buckets view owns a fresh render token
        try:
            response = self.s3_manager.client.list_buckets()
            items = [dict(type="bucket", name=b['Name']) for b in response['Buckets']]
            self._current_items = items  # cache for re-render
            self._render_items_incrementally(items, None, "__buckets__")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def enter_bucket(self, bucket_name):
        if self.current_bucket != bucket_name:
            self.current_prefix = ""
        self.current_bucket = bucket_name
        self._current_items = None  # invalidate cache — will re-fetch from S3
        self.update_breadcrumbs()
        self.clear_list_frame()

        # A token lets a slow fetch know it was superseded by newer navigation.
        self._load_token = token = object()
        self._show_loading(True)

        def fetch():
            # Network call runs off the UI thread so the window never freezes
            # while waiting on S3.
            try:
                paginator = self.s3_manager.client.get_paginator('list_objects_v2')
                folders, files = [], []
                for page in paginator.paginate(Bucket=bucket_name, Prefix=self.current_prefix, Delimiter='/'):
                    if token is not getattr(self, "_load_token", None):
                        return
                    if 'CommonPrefixes' in page:
                        for cp in page['CommonPrefixes']:
                            folder_name = cp['Prefix'].rstrip('/').split('/')[-1]
                            folders.append(dict(type="folder", name=folder_name,
                                                full_path=cp['Prefix'], mtime=None))
                    if 'Contents' in page:
                        for obj in page['Contents']:
                            if obj['Key'] != self.current_prefix:
                                file_name = obj['Key'].split('/')[-1]
                                size_kb = round(obj['Size'] / 1024, 2)
                                _, ext = os.path.splitext(file_name)
                                last_mod = obj.get('LastModified')
                                date_str = last_mod.strftime("%Y-%m-%d %H:%M") if last_mod else ""
                                files.append(dict(type="file", name=file_name, full_path=obj['Key'],
                                                  size=f"{size_kb} KB", ext=ext, date=date_str,
                                                  mtime=last_mod, size_bytes=obj['Size']))
            except Exception as e:
                self.after(0, lambda: self._on_listing_error(token))
                return

            if token is not getattr(self, "_load_token", None):
                return
            items = self._sort_items(folders, files)
            # Hand rendering back to the UI thread.
            self.after(0, lambda: self._on_listing_ready(token, bucket_name,
                                                         self.current_prefix, items))

        threading.Thread(target=fetch, daemon=True).start()

    def _on_listing_error(self, token):
        if token is not getattr(self, "_load_token", None):
            return
        self._show_loading(False)
        self.list_buckets()

    def _on_listing_ready(self, token, bucket_name, prefix, items):
        # Ignore results from a navigation the user already moved past.
        if token is not getattr(self, "_load_token", None):
            return
        self._show_loading(False)
        self._current_items = items  # cache for re-render without S3 re-fetch
        self._file_sizes = {
            it["full_path"]: it["size_bytes"] for it in items if "size_bytes" in it
        }
        self._render_items_incrementally(items, bucket_name, prefix)
        self.save_session()

    def _rerender_current_view(self):
        """Re-sort and re-draw the current listing from cached data (no S3 call)."""
        items = getattr(self, "_current_items", None)
        if not items:
            if self.current_bucket:
                self.enter_bucket(self.current_bucket)
            elif self.s3_manager:
                self.list_buckets()
            return
        self.clear_list_frame()
        self._file_sizes = {
            it["full_path"]: it["size_bytes"] for it in items if "size_bytes" in it
        }
        if self.current_bucket:
            folders = [it for it in items if it["type"] == "folder"]
            files = [it for it in items if it["type"] == "file"]
            sorted_items = self._sort_items(folders, files)
        else:
            sorted_items = items
        self._render_items_incrementally(
            sorted_items, self.current_bucket,
            self.current_prefix if self.current_bucket else "__buckets__")

    def _show_loading(self, show):
        """A lightweight centered loading indicator over the file area."""
        if show:
            if getattr(self, "_loading_lbl", None) is not None:
                return
            self._loading_lbl = ctk.CTkLabel(
                self.file_list_frame, text=t("lbl_loading"), font=design.Type.TITLE,
                text_color=Color.TEXT_MUTED)
            self._loading_lbl.grid(row=0, column=0, columnspan=self.columns_per_row, pady=60)
        else:
            lbl = getattr(self, "_loading_lbl", None)
            if lbl is not None:
                lbl.destroy()
                self._loading_lbl = None

    def _sort_items(self, folders, files):
        """Order the listing. Folders always come first, sorted by name (S3
        gives no timestamp for folder prefixes). Files follow, ordered by the
        current sort mode.

        - "recent": most recently modified first (default).
        - "name":   A-Z by file name.
        """
        folders = sorted(folders, key=lambda it: it["name"].lower())
        mode = getattr(self, "sort_mode", "recent")
        if mode == "name":
            files = sorted(files, key=lambda it: it["name"].lower())
        else:  # recent first; items without a timestamp sink to the bottom
            from datetime import datetime, timezone
            oldest = datetime.min.replace(tzinfo=timezone.utc)
            files = sorted(files, key=lambda it: it.get("mtime") or oldest, reverse=True)
        return folders + files

    def _render_items_incrementally(self, items, bucket, prefix, batch=20):
        """Render cards in small batches so they visibly stream in.

        Each batch is drawn, then we hand control back to the event loop with
        after(10, ...) before the next one. That lets Tk paint the batch (so the
        user sees items appearing) and keeps the window responsive. Crucially we
        do NOT call update_idletasks() per item - that forced a scrollbar
        repaint on every card and was the old O(n^2) freeze. Yielding via after(10)
        lets the mainloop repaint once per batch and process input without freezing.

        A token guards against races: navigating elsewhere mid-stream abandons
        the stale render instead of drawing into the wrong folder.
        """
        flf = self.file_list_frame
        token = getattr(self, "_load_token", None)
        total = len(items)

        if total == 0:
            msg = t("lbl_empty_folder") if prefix else t("lbl_no_subfolders")
            lbl = ctk.CTkLabel(flf, text=msg, font=Type.BODY, text_color=Color.TEXT_FAINT)
            if self.view_mode == "grid":
                lbl.grid(row=0, column=0, columnspan=self.columns_per_row, pady=Space.XL)
            else:
                lbl.pack(pady=Space.XL)
            return

        def draw_batch(start):
            if token is not getattr(self, "_load_token", None):
                return  # superseded by newer navigation
            end = min(start + batch, total)
            for it in items[start:end]:
                self.create_list_item(
                    it["type"], it["name"], full_path=it.get("full_path"),
                    size=it.get("size", ""), ext=it.get("ext", ""), date=it.get("date", ""))
            if end < total:
                # Brief inline progress while the rest streams in.
                self._show_count_hint(end, total)
                self.after(10, lambda: draw_batch(end))
            else:
                self._clear_count_hint()

        draw_batch(0)

    def _show_count_hint(self, done, total):
        """Tiny inline 'done/total' hint shown while items stream in."""
        hint = getattr(self, "_count_hint", None)
        text = f"{done}/{total}"
        if hint is None:
            self._count_hint = ctk.CTkLabel(
                self.main_view, text=text, font=Type.CAPTION,
                fg_color=Color.SUBTLE, text_color=Color.TEXT_MUTED,
                corner_radius=RADIUS_SM, padx=Space.SM, pady=2)
            self._count_hint.place(relx=0.5, rely=1.0, anchor="s", y=-70)
        else:
            hint.configure(text=text)

    def _clear_count_hint(self):
        hint = getattr(self, "_count_hint", None)
        if hint is not None:
            hint.destroy()
            self._count_hint = None

    def copy_link(self, full_path):
        try:
            web_friendly_url = self._build_link(full_path)
            self.clipboard_clear()
            self.clipboard_append(web_friendly_url)
            self.update()
            messagebox.showinfo(t("msg_copied_title"), t("msg_link_copied"))
        except Exception as e:
            messagebox.showerror(t("lbl_error"), f"{t('msg_error_link')}: {str(e)}")

    def _build_link(self, full_path):
        """Return a shareable URL for an object key (CloudFront or presigned)."""
        cloudfront_base = getattr(self, "cloudfront_url", "").strip().rstrip("/")
        if cloudfront_base:
            # Clean CloudFront URL: base + "/" + key (spaces as +)
            encoded_key = full_path.replace(" ", "+")
            return f"{cloudfront_base}/{encoded_key}"
        # Fallback: S3 presigned URL with query params stripped
        url = self.s3_manager.client.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': self.current_bucket, 'Key': full_path},
        )
        return url.split('?')[0].replace("%20", "+")

    def copy_selected_links(self):
        """Copy, per selected file, its name (no extension) then its link.

        Each file produces two lines - name without extension, then the URL -
        and blocks are separated by a blank line so several files stay readable:

            photo
            https://.../photo.jpg

            report
            https://.../report.pdf
        """
        files = [(fp, nm) for (fp, tp, nm) in self.selected_items if tp == "file"]
        if not files:
            messagebox.showwarning(t("msg_empty_sel_title"), t("msg_select_files_for_links"))
            return
        blocks, links_ok, errors = [], 0, 0
        for full_path, name in sorted(files, key=lambda x: x[1].lower()):
            try:
                link = self._build_link(full_path)
            except Exception:
                errors += 1
                continue
            name_no_ext = os.path.splitext(name)[0]
            blocks.append(f"{name_no_ext}\n{link}")
            links_ok += 1
        if not blocks:
            messagebox.showerror(t("lbl_error"), t("msg_error_link"))
            return
        self.clipboard_clear()
        self.clipboard_append("\n\n".join(blocks))
        self.update()
        msg = f"{links_ok}{t('msg_links_copied_count')}"
        if errors:
            msg += f"\n{errors}{t('msg_links_failed_count')}"
        messagebox.showinfo(t("msg_copied_title"), msg)

    def _get_download_dir(self):
        # Powerfully get system Downloads folder
        if os.name == 'nt':
            import ctypes.wintypes
            CSIDL_PERSONAL = 5 
            CSIDL_DOWNLOADS = 40 
            SHGFP_TYPE_CURRENT = 0
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_DOWNLOADS, None, SHGFP_TYPE_CURRENT, buf)
            return buf.value
        else:
            download_dir = ""
            # 1. Try to use xdg-user-dir
            try:
                import subprocess
                result = subprocess.run(['xdg-user-dir', 'DOWNLOAD'], capture_output=True, text=True)
                if result.returncode == 0:
                    download_dir = result.stdout.strip()
            except Exception: pass

            # 2. Config parsing
            if not download_dir or not os.path.exists(download_dir):
                 try:
                    config_path = os.path.join(os.path.expanduser("~"), ".config", "user-dirs.dirs")
                    if os.path.exists(config_path):
                        with open(config_path, "r") as f:
                            for line in f:
                                if line.startswith("XDG_DOWNLOAD_DIR"):
                                    parts = line.split('=')
                                    if len(parts) > 1:
                                        raw_path = parts[1].strip().strip('"')
                                        download_dir = raw_path.replace("$HOME", os.path.expanduser("~"))
                                        break
                 except: pass
            
            # 3. Fallbacks
            if not download_dir or not os.path.exists(download_dir):
                candidates = [
                    os.path.join(os.path.expanduser("~"), "Descargas"),
                    os.path.join(os.path.expanduser("~"), "Downloads"),
                    os.path.join(os.path.expanduser("~"), "Desktop"),
                    os.path.join(os.path.expanduser("~"), "Escritorio"),
                    os.path.expanduser("~")
                ]
                for c in candidates:
                    if os.path.exists(c):
                        download_dir = c
                        break
            
            return download_dir

    def download_file(self, full_path, file_name):
        try:
            download_dir = self._get_download_dir()
            local_path = os.path.join(download_dir, file_name)
            
            # Avoid silent overwrite (optional, but good practice)
            if os.path.exists(local_path):
                base, ext = os.path.splitext(local_path)
                counter = 1
                while os.path.exists(local_path):
                    local_path = f"{base}_{counter}{ext}"
                    counter += 1
            
            def perform_download():
                self.after(0, lambda: self.show_progress(True))
                self.after(0, lambda: self.prog_label.configure(text=f"{t('msg_starting_download')} {file_name}..."))
                try:
                    # 1. Get total size from cache or head_object
                    total_bytes = self._file_sizes.get(full_path)
                    if total_bytes is None:
                        head = self.s3_manager.client.head_object(Bucket=self.current_bucket, Key=full_path)
                        total_bytes = head.get('ContentLength', 0)

                    # 2. Throttled progress callback (keeps the UI responsive)
                    progress_tracker = self.make_progress_tracker(total_bytes, t("msg_downloading"))

                    # 3. Download using optimized TransferConfig
                    self.s3_manager.download_file(
                        self.current_bucket, full_path, local_path,
                        progress_cb=progress_tracker, known_size=total_bytes
                    )
                    
                    self.after(0, lambda: messagebox.showinfo(t("msg_download_success_title"), f"{t('msg_file_saved_at')}:\n{local_path}"))
                    self.after(0, lambda: self.prog_label.configure(text=t("msg_download_complete")))
                    self.after(0, lambda: self.prog_bar.set(0))
                    self.after(1200, lambda: self.show_progress(False))
                except Exception as e_inner:
                    # Capture the error string immediately to avoid closure scoping issues
                    err_msg = str(e_inner)
                    self.after(0, lambda m=err_msg: messagebox.showerror(t("msg_download_error_title"), m))
                    self.after(0, lambda: self.prog_label.configure(text=t("msg_download_error")))
                    self.after(1200, lambda: self.show_progress(False))

            threading.Thread(target=perform_download, daemon=True).start()
            
        except Exception as e:
            messagebox.showerror(t("lbl_error"), f"{t('msg_fail_start_download')}: {str(e)}")

    def download_selected_items(self):
        if not self.selected_items:
            messagebox.showwarning(t("msg_empty_sel_title"), t("msg_select_at_least_one"))
            return

        # Automatic destination: Downloads folder
        dest_dir = self._get_download_dir()
        if not dest_dir: 
             messagebox.showerror(t("lbl_error"), t("msg_no_downloads_folder"))
             return

        threading.Thread(target=self.hilo_bulk_download, args=(dest_dir,), daemon=True).start()

    def hilo_bulk_download(self, dest_dir):
        # 1. Resolve all items to download (flatten folders)
        items_to_process = [] # List of (s3_key, local_path_abs, s3_size)
        total_bytes = 0

        self.after(0, lambda: self.show_progress(True))
        self.after(0, lambda: self.prog_label.configure(text=t("msg_calc_total_size")))
        self.after(0, lambda: self.prog_bar.configure(mode="indeterminate"))
        self.after(0, lambda: self.prog_bar.start())

        try:
             # Backup of selected items
             selection = list(self.selected_items)
             
             for (full_path, type, name) in selection:
                 if type == "file":
                     # Fast size lookup from view cache or single fallback
                     sz = self._file_sizes.get(full_path)
                     if sz is None:
                         try:
                             head = self.s3_manager.client.head_object(Bucket=self.current_bucket, Key=full_path)
                             sz = head.get('ContentLength', 0)
                         except:
                             sz = 0
                     local_tgt = os.path.join(dest_dir, name)
                     # Handle duplicates in root
                     base, ext = os.path.splitext(local_tgt)
                     c_dup = 1
                     while os.path.exists(local_tgt):
                          local_tgt = f"{base}_{c_dup}{ext}"
                          c_dup += 1
                     
                     items_to_process.append((full_path, local_tgt, sz))
                     total_bytes += sz
                 
                 elif type == "folder":
                     # Recursive listing
                     paginator = self.s3_manager.client.get_paginator('list_objects_v2')
                     # The local destination folder will be dest_dir/folder_name
                     local_folder_root = os.path.join(dest_dir, name)
                     if not os.path.exists(local_folder_root):
                         os.makedirs(local_folder_root, exist_ok=True)
                     
                     for page in paginator.paginate(Bucket=self.current_bucket, Prefix=full_path):
                         if 'Contents' in page:
                             for obj in page['Contents']:
                                 k = obj['Key']
                                 # Skip if it is the folder itself (0 bytes marker)
                                 if k == full_path: continue
                                 
                                 sz = obj.get('Size', 0)
                                 # Calculate relative path from the selected full_path
                                 rel_path = os.path.relpath(k, full_path)
                                 local_tgt = os.path.join(local_folder_root, rel_path)
                                 
                                 # Create subdirectories if necessary
                                 ldir = os.path.dirname(local_tgt)
                                 if not os.path.exists(ldir):
                                     os.makedirs(ldir, exist_ok=True)
                                     
                                 items_to_process.append((k, local_tgt, sz))
                                 total_bytes += sz

             # 2. Throttled progress callback shared across all files
             tracker = self.make_progress_tracker(total_bytes, t("msg_downloading"))

             # Switch from indeterminate (size calc) to determinate (transfer)
             self.after(0, lambda: self.prog_bar.stop())
             self.after(0, lambda: self.prog_bar.configure(mode="determinate"))

             # 3. Execute Downloads concurrently
             completed_count = 0
             counter_lock = threading.Lock()
             total_items_count = len(items_to_process)

             def _download_worker(item):
                 nonlocal completed_count
                 k, local, sz = item
                 fname = os.path.basename(local)
                 try:
                     self.s3_manager.client.download_file(
                         self.current_bucket, k, local,
                         Config=DEFAULT_TRANSFER_CONFIG,
                         Callback=tracker
                     )
                     if sz == 0:
                         tracker.add_bytes(0)
                 except Exception as err:
                     print(f"Error downloading {k}: {err}")
                 finally:
                     with counter_lock:
                         completed_count += 1
                         current_c = completed_count
                     tracker.set_file_context(current_c, total_items_count, fname)

             max_w = min(6, total_items_count) if total_items_count > 0 else 1
             with concurrent.futures.ThreadPoolExecutor(max_workers=max_w) as executor:
                 list(executor.map(_download_worker, items_to_process))
            
             self.after(0, lambda: messagebox.showinfo(t("msg_bulk_down_title"), f"{t('msg_downloaded_count_1')}{len(items_to_process)}{t('msg_downloaded_count_2')}"))
             self.after(0, lambda: self.prog_label.configure(text=t("msg_bulk_down_complete")))
             self.after(0, lambda: self.prog_bar.set(0))
             self.after(1200, lambda: self.show_progress(False))
             # Clear selection
             self.selection_clear_ui()

        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self.prog_bar.stop())
            self.after(0, lambda: self.prog_bar.configure(mode="determinate"))
            self.after(0, lambda: self.show_progress(False))
            self.after(0, lambda: messagebox.showerror(t("lbl_error"), msg))

    def selection_clear_ui(self):
        self.selected_items.clear()
        # Refresh view to remove checks using cached data (no S3 re-fetch)
        self.after(0, lambda: self._rerender_current_view())

    def toggle_theme(self):
        # Icons already carry both light and dark renderings, and every widget
        # color is a (light, dark) tuple, so CustomTkinter restyles everything
        # instantly. No rebuild, no icon re-render: this is why it no longer
        # stutters when switching themes.
        mode = "light" if self.theme_switch.get() == 1 else "dark"
        ctk.set_appearance_mode(mode)
        self.theme_switch.configure(
            text=t("sw_light_mode") if mode == "dark" else t("sw_dark_mode"))
        # Persist so the choice survives a restart.
        self.save_session()

    def _resolve_icon(self, type, ext):
        """Return (icon_name, color_tuple) for a list item.

        Content icons (folder / bucket / file types) get a flat color so the
        grid reads at a glance; the palette stays in one calm register so it's
        colorful without being noisy. Action icons remain neutral elsewhere.
        """
        if type == "bucket":
            return "bucket", design.IconColor.BUCKET
        if type == "folder":
            return "folder", design.IconColor.FOLDER
        name = design.EXT_ICON.get((ext or "").lower().strip("."), "file")
        color = design.ICON_COLOR_BY_NAME.get(name, design.IconColor.GENERIC)
        return name, color

    def _icon_action_button(self, parent, icon_name, color, command, tip_color=None):
        return ctk.CTkButton(
            parent, text="", image=design.icon(icon_name, 16, tip_color or Color.TEXT_MUTED),
            width=30, height=30, fg_color="transparent", hover_color=Color.CONTROL_HOVER,
            corner_radius=RADIUS_SM, command=command)

    def create_list_item(self, type, name, full_path=None, size="", ext="", date=""):
        self.grid_idx += 1
        icon_name, icon_color = self._resolve_icon(type, ext)
        selectable = type in ("file", "folder")
        is_selected = (full_path, type, name) in self.selected_items

        if type == "bucket":
            open_cmd = lambda: self.enter_bucket(name)
        elif type == "folder":
            open_cmd = lambda: self.enter_subfolder(full_path)
        else:
            open_cmd = None

        # ---------------------------------------------------------------
        # LIST VIEW: a single row, left-aligned, generous whitespace
        # ---------------------------------------------------------------
        if self.view_mode == "list":
            card = ctk.CTkFrame(self.file_list_frame, corner_radius=RADIUS,
                                fg_color=Color.SUBTLE if is_selected else "transparent")
            card.grid(row=self.grid_idx, column=0, columnspan=self.columns_per_row,
                      padx=0, pady=1, sticky="ew")
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=Space.MD, pady=Space.SM)

            if selectable:
                chk = ctk.CTkCheckBox(
                    row, text="", width=20, checkbox_width=18, checkbox_height=18, corner_radius=4,
                    fg_color=Color.ACCENT, hover_color=Color.ACCENT_HOVER, border_color=Color.LINE_STRONG,
                    command=lambda tp=type, n=name, p=full_path: self.toggle_selection(tp, n, p))
                chk.pack(side="left", padx=(0, Space.MD))
                if is_selected:
                    chk.select()

            icon_btn = ctk.CTkButton(
                row, text="", image=design.icon(icon_name, 20, icon_color), width=28, height=28,
                fg_color="transparent", hover=bool(open_cmd), hover_color=Color.CONTROL_HOVER,
                corner_radius=RADIUS_SM, command=open_cmd)
            icon_btn.pack(side="left", padx=(0, Space.MD))

            name_btn = ctk.CTkButton(
                row, text=name, anchor="w", font=Type.BODY, text_color=Color.TEXT,
                fg_color="transparent", hover=False, command=open_cmd)
            name_btn.pack(side="left", fill="x", expand=True)

            if type != "bucket":
                actions = ctk.CTkFrame(row, fg_color="transparent")
                actions.pack(side="right")
                if type == "file":
                    self._icon_action_button(actions, "link", Color.TEXT_MUTED, lambda p=full_path: self.copy_link(p)).pack(side="left")
                    self._icon_action_button(actions, "download", Color.TEXT_MUTED, lambda p=full_path, n=name: self.download_file(p, n)).pack(side="left")
                self._icon_action_button(actions, "rename", Color.TEXT_MUTED, lambda n=name, tp=type, p=full_path: self.request_rename(n, tp, p)).pack(side="left")
                self._icon_action_button(actions, "trash", Color.DANGER, lambda n=name, tp=type, p=full_path: self.request_delete(n, tp, p), tip_color=Color.DANGER).pack(side="left")

                ctk.CTkLabel(row, text=date, font=Type.CAPTION, text_color=Color.TEXT_FAINT,
                             width=130, anchor="e").pack(side="right", padx=Space.SM)
                if type == "file":
                    ctk.CTkLabel(row, text=size, font=Type.MONO, text_color=Color.TEXT_MUTED,
                                 width=90, anchor="e").pack(side="right", padx=Space.SM)
            return card

        # ---------------------------------------------------------------
        # GRID VIEW: compact square cards, icon-forward
        # ---------------------------------------------------------------
        row_i = (self.grid_idx - 1) // self.columns_per_row
        col_i = (self.grid_idx - 1) % self.columns_per_row

        card = ctk.CTkFrame(
            self.file_list_frame, corner_radius=RADIUS, border_width=1,
            fg_color=Color.SURFACE,
            border_color=Color.ACCENT if is_selected else Color.LINE)
        card.grid(row=row_i, column=col_i, padx=Space.SM, pady=Space.SM, sticky="nsew")

        if selectable:
            chk = ctk.CTkCheckBox(
                card, text="", width=18, checkbox_width=16, checkbox_height=16, corner_radius=4,
                fg_color=Color.ACCENT, hover_color=Color.ACCENT_HOVER, border_color=Color.LINE_STRONG,
                command=lambda tp=type, n=name, p=full_path: self.toggle_selection(tp, n, p))
            chk.place(x=Space.SM, y=Space.SM)
            if is_selected:
                chk.select()

        icon_btn = ctk.CTkButton(
            card, text="", image=design.icon(icon_name, 44, icon_color), width=60, height=60,
            fg_color="transparent", hover=bool(open_cmd), hover_color=Color.CONTROL_HOVER,
            corner_radius=RADIUS, command=open_cmd)
        icon_btn.pack(side="top", pady=(Space.XL, Space.SM), padx=Space.MD)

        # Use a wrapping label for the name so long keys don't blow out the card.
        display_name = name if len(name) <= 26 else name[:24] + "…"
        name_lbl = ctk.CTkLabel(card, text=display_name, font=Type.LABEL, text_color=Color.TEXT,
                                wraplength=120, justify="center")
        name_lbl.pack(side="top", padx=Space.SM)
        if open_cmd:
            name_lbl.bind("<Button-1>", lambda _e: open_cmd())

        if type == "bucket":
            ctk.CTkFrame(card, fg_color="transparent", height=Space.MD).pack(side="top")
            return card

        meta = size if type == "file" else ""
        ctk.CTkLabel(card, text=meta, font=Type.MONO, text_color=Color.TEXT_FAINT).pack(side="top", pady=(Space.XS, 0))

        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.pack(side="top", pady=(Space.SM, Space.MD))
        if type == "file":
            self._icon_action_button(footer, "link", Color.TEXT_MUTED, lambda p=full_path: self.copy_link(p)).pack(side="left", padx=1)
            self._icon_action_button(footer, "download", Color.TEXT_MUTED, lambda p=full_path, n=name: self.download_file(p, n)).pack(side="left", padx=1)
        self._icon_action_button(footer, "rename", Color.TEXT_MUTED, lambda n=name, tp=type, p=full_path: self.request_rename(n, tp, p)).pack(side="left", padx=1)
        self._icon_action_button(footer, "trash", Color.DANGER, lambda n=name, tp=type, p=full_path: self.request_delete(n, tp, p), tip_color=Color.DANGER).pack(side="left", padx=1)
        return card

    def open_move_modal(self, items_to_move):
        if not items_to_move:
            messagebox.showwarning("Aviso", "No hay elementos para mover.")
            return
        MoveModal(self, self.s3_manager, items_to_move, self.current_bucket, self.current_prefix, self.execute_move)

    def move_selected_items(self):
        self.open_move_modal(self.selected_items)

    def execute_move(self, items, tgt_bucket, tgt_prefix):
        self.show_progress(True)
        self.prog_bar.set(0)
        self.prog_label.configure(text=f"{t('msg_move_title')}: {len(items)}...")
        self.prog_bar.configure(mode="indeterminate")
        self.prog_bar.start()
        
        # Disable buttons temporarily
        self.btn_move_sel.configure(state="disabled")
        
        threading.Thread(target=self.hilo_bulk_move, args=(items, tgt_bucket, tgt_prefix), daemon=True).start()

    def hilo_bulk_move(self, items, tgt_bucket, tgt_prefix):
        try:
            files = [it for it in items if it[1] == "file"]
            folders = [it for it in items if it[1] != "file"]
            total = len(items)
            completed = 0
            lock = threading.Lock()

            def update_progress(current_name):
                nonlocal completed
                with lock:
                    completed += 1
                    pct = completed / total if total else 1.0
                    self.after(0, lambda p=pct, c=completed, tot=total, n=current_name: (
                        self.prog_bar.set(p),
                        self.prog_label.configure(text=f"{t('msg_move_title')}: {c}/{tot} • {n}")
                    ))

            # 1. Parallel move for individual files
            if files:
                self.after(0, lambda: self.prog_bar.stop())
                self.after(0, lambda: self.prog_bar.configure(mode="determinate"))

                def move_one_file(item):
                    src_path, _, current_name = item
                    new_key = tgt_prefix + current_name
                    self.s3_manager.move_object(self.current_bucket, src_path, tgt_bucket, new_key)
                    update_progress(current_name)

                max_w = min(10, len(files))
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_w) as executor:
                    list(executor.map(move_one_file, files))

            # 2. Parallel move for folders (each folder handles its keys concurrently)
            for item in folders:
                src_path, _, current_name = item
                new_key = tgt_prefix + current_name
                if not new_key.endswith('/'): new_key += '/'
                self.s3_manager.move_folder_parallel(
                    self.current_bucket, src_path, tgt_bucket, new_key
                )
                update_progress(current_name)
            
            # Reset selection and refresh UI
            self.selected_items.clear()
            self.after(0, lambda: self.enter_bucket(self.current_bucket))
            self.after(0, lambda: messagebox.showinfo(t("msg_move_complete_title"), f"{t('msg_objects_moved_to')}{tgt_bucket}/{tgt_prefix}."))
        except Exception as e:
            self.after(0, lambda err=e: messagebox.showerror(t("msg_err_moving_title"), str(err)))
        finally:
            self.after(0, self.prog_bar.stop)
            self.after(0, lambda: self.prog_bar.configure(mode="determinate"))
            self.after(0, lambda: self.prog_label.configure(text=t("lbl_ready")))
            self.after(800, lambda: self.show_progress(False))
            self.after(0, lambda: self.btn_move_sel.configure(state="normal"))

    def request_rename(self, name, type, full_path):
        target_bucket = self.current_bucket
        target_prefix = self.current_prefix
        if type == "file":
            base_name, ext = os.path.splitext(name)
            dialog = PromptDialog(
                initial_value=base_name,
                text=f"{t('msg_new_name_for')}{base_name}{t('msg_extension_1')}{ext}{t('msg_extension_2')}",
                title=t("msg_rename_title")
            )
            new_base = dialog.get_input()
            if new_base and new_base != base_name:
                new_name = new_base + ext
                threading.Thread(target=self.perform_rename, args=(name, new_name, type, full_path, target_bucket, target_prefix), daemon=True).start()
        else:
            dialog = PromptDialog(
                initial_value=name,
                text=f"{t('msg_new_folder_name_for')}{name}':",
                title=t("msg_rename_title")
            )
            new_name = dialog.get_input()
            if new_name and new_name != name:
                threading.Thread(target=self.perform_rename, args=(name, new_name, type, full_path, target_bucket, target_prefix), daemon=True).start()

    def perform_rename(self, old_name, new_name, type, full_path, target_bucket, target_prefix):
        self.after(0, lambda: self.show_progress(True))
        self.after(0, lambda: self.prog_label.configure(text=f"{t('msg_renaming_1')}{old_name}{t('msg_renaming_2')}{new_name}'..."))
        self.after(0, lambda: self.prog_bar.configure(mode="indeterminate"))
        self.after(0, lambda: self.prog_bar.start())
        try:
            if type == "folder":
                parent = "/".join(full_path.strip('/').split('/')[:-1])
                parent = parent + "/" if parent else ""
                new_key_base = parent + new_name + "/"
                
                def on_rename_progress(done, total):
                    pct = done / total if total else 1.0
                    self.after(0, lambda p=pct, d=done, tot=total: (
                        self.prog_bar.set(p),
                        self.prog_label.configure(text=f"{t('msg_renaming_1')}{old_name} ({d}/{tot})...")
                    ))

                self.after(0, lambda: self.prog_bar.stop())
                self.after(0, lambda: self.prog_bar.configure(mode="determinate"))
                self.s3_manager.rename_folder_parallel(
                    target_bucket, full_path, new_key_base,
                    progress_cb=on_rename_progress
                )
            else:
                parent = "/".join(full_path.split('/')[:-1])
                parent = parent + "/" if parent else ""
                new_key = parent + new_name
                self.s3_manager.client.copy_object(Bucket=target_bucket, CopySource={'Bucket': target_bucket, 'Key': full_path}, Key=new_key)
                self.s3_manager.client.delete_object(Bucket=target_bucket, Key=full_path)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror(t("msg_err_renaming_title"), str(e)))
        finally:
            self.after(0, lambda: self.prog_bar.stop())
            self.after(0, lambda: self.prog_bar.configure(mode="determinate"))
            self.after(0, lambda: self.prog_label.configure(text=t("lbl_ready")))
            self.after(0, lambda: self.prog_bar.set(0))
            self.after(800, lambda: self.show_progress(False))
            if self.current_bucket == target_bucket and self.current_prefix == target_prefix:
                self.after(0, lambda: self.enter_bucket(self.current_bucket))

    def request_delete(self, name, type, full_path):
        if self._check_delete_pin(f"{t('msg_pass_to_delete')}{name}':"):
            if messagebox.askyesno(t("msg_confirm_del_title"), f"{t('msg_sure_to_delete_1')}{name}{t('msg_sure_to_delete_2')}"):
                target_bucket = self.current_bucket
                target_prefix = self.current_prefix
                import threading
                threading.Thread(target=self.perform_delete, args=(full_path, type, target_bucket, target_prefix), daemon=True).start()

    def perform_delete(self, key, type, target_bucket, target_prefix):
        try:
            if type == "file":
                self.s3_manager.client.delete_object(Bucket=target_bucket, Key=key)
            else:
                paginator = self.s3_manager.client.get_paginator('list_objects_v2')
                for page in paginator.paginate(Bucket=target_bucket, Prefix=key):
                    if 'Contents' in page:
                         objects = [{'Key': obj['Key']} for obj in page['Contents']]
                         self.s3_manager.client.delete_objects(Bucket=target_bucket, Delete={'Objects': objects})
            
            if self.current_bucket == target_bucket and self.current_prefix == target_prefix:
                self.after(0, lambda: self.enter_bucket(self.current_bucket))
        except Exception as e:
            self.thumbnail_cache.clear()
            messagebox.showerror(t("lbl_error"), str(e))

    def delete_selected_items(self):
        """Delete every selected item, asking for the delete PIN only once."""
        if not self.selected_items:
            messagebox.showwarning(t("msg_empty_sel_title"), t("msg_select_at_least_one"))
            return

        items = list(self.selected_items)
        if not self._check_delete_pin(
                f"{t('msg_pass_to_delete_n_1')}{len(items)}{t('msg_pass_to_delete_n_2')}"):
            return

        if not messagebox.askyesno(
                t("msg_confirm_del_title"),
                f"{t('msg_sure_to_delete_n_1')}{len(items)}{t('msg_sure_to_delete_n_2')}"):
            return

        target_bucket = self.current_bucket
        target_prefix = self.current_prefix
        threading.Thread(
            target=self.perform_bulk_delete,
            args=(items, target_bucket, target_prefix), daemon=True).start()

    def perform_bulk_delete(self, items, target_bucket, target_prefix):
        self.after(0, lambda: self.show_progress(True))
        self.after(0, lambda: self.prog_label.configure(
            text=f"{t('msg_confirm_del_title')}: {len(items)}..."))
        self.after(0, lambda: self.prog_bar.configure(mode="indeterminate"))
        self.after(0, lambda: self.prog_bar.start())
        errors = 0
        try:
            # 1. Batch delete all individual files at once
            file_keys = [path for (path, itype, _name) in items if itype == "file"]
            if file_keys:
                try:
                    self.s3_manager.delete_files_batch(target_bucket, file_keys)
                except Exception as e:
                    print(f"Error in batch file deletion: {e}")
                    errors += len(file_keys)

            # 2. Delete folders using paginated batch delete
            folder_items = [path for (path, itype, _name) in items if itype != "file"]
            for fpath in folder_items:
                try:
                    self.s3_manager.delete_folder(target_bucket, fpath)
                except Exception as e:
                    print(f"Error deleting folder {fpath}: {e}")
                    errors += 1

            self.selected_items.clear()
            done = max(0, len(items) - errors)
            self.after(0, lambda: messagebox.showinfo(
                t("msg_success_title"), f"{done}{t('msg_deleted_count')}"))
        finally:
            self.after(0, lambda: self.prog_bar.stop())
            self.after(0, lambda: self.prog_bar.configure(mode="determinate"))
            self.after(0, lambda: self.prog_label.configure(text=t("lbl_ready")))
            self.after(800, lambda: self.show_progress(False))
            if self.current_bucket == target_bucket and self.current_prefix == target_prefix:
                self.after(0, lambda: self.enter_bucket(self.current_bucket))

    def enter_subfolder(self, prefix):
        self.current_prefix = prefix
        self.enter_bucket(self.current_bucket)

    def go_back(self):
        if self.current_prefix:
            parts = self.current_prefix.strip('/').split('/')
            self.current_prefix = "/".join(parts[:-1]) + "/" if len(parts) > 1 else ""
            self.enter_bucket(self.current_bucket)
        else:
            self.list_buckets()

    def create_folder_task(self):
        if not self.current_bucket: return
        name = ctk.CTkInputDialog(text=t("msg_folder_name_input"), title=t("msg_new_folder_title")).get_input()
        if name:
            full_key = self.current_prefix + name.strip().replace("/", "") + "/"
            try:
                self.s3_manager.client.put_object(Bucket=self.current_bucket, Key=full_key)
                self.enter_bucket(self.current_bucket)
            except Exception as e:
                messagebox.showerror(t("lbl_error"), str(e))

    def upload_task(self, type, paths_arg=None):
        if not self.current_bucket: return
        
        if type == "files":
            paths = filedialog.askopenfilenames()
        elif type == "folder":
            d = filedialog.askdirectory()
            paths = [d] if d else []
        else:
            paths = paths_arg
            
        if paths:
            if isinstance(paths, str): paths = [paths]
            paths = [p for p in paths if p and str(p).strip()]
            if paths:
                threading.Thread(target=self.hilo_upload, args=(paths, type), daemon=True).start()

    def hilo_upload(self, paths, type):
        if isinstance(paths, tuple): paths = list(paths)
        storage = self.storage_menu.get()
        files_to_upload = []

        # 1. Collect files and calculate total size
        total_size_bytes = 0
        for p in paths:
            if not p: continue
            if os.path.isfile(p):
                 sz = os.path.getsize(p)
                 files_to_upload.append((p, os.path.basename(p), sz))
                 total_size_bytes += sz
            elif os.path.isdir(p):
                 for root, _, files in os.walk(p):
                    for f in files:
                        full = os.path.join(root, f)
                        sz = os.path.getsize(full)
                        rel = os.path.relpath(full, os.path.dirname(p))
                        files_to_upload.append((full, rel.replace("\\", "/"), sz))
                        total_size_bytes += sz

        total_files = len(files_to_upload)
        if total_files == 0:
            return

        self.after(0, lambda: self.show_progress(True))

        # 2. Throttled progress callback (keeps the UI responsive during uploads)
        progress_tracker = self.make_progress_tracker(
            total_size_bytes, t("msg_uploading").strip().rstrip("."))

        # 3. Upload with ThreadPoolExecutor
        completed_count = 0
        counter_lock = threading.Lock()

        def _upload_worker(item):
            nonlocal completed_count
            local, s3_key, fsize = item
            final_key = self.current_prefix + s3_key
            fname = os.path.basename(local)
            
            content_type, _ = mimetypes.guess_type(local)
            if content_type is None:
                content_type = 'application/octet-stream'

            try:
                self.s3_manager.client.upload_file(
                    local, self.current_bucket, final_key,
                    ExtraArgs={'StorageClass': storage, 'ContentType': content_type},
                    Config=DEFAULT_TRANSFER_CONFIG,
                    Callback=progress_tracker
                )
                if fsize == 0:
                    progress_tracker.add_bytes(0)
            except Exception as e:
                print(f"Error {s3_key}: {e}")
            finally:
                with counter_lock:
                    completed_count += 1
                    current_c = completed_count
                progress_tracker.set_file_context(current_c, total_files, fname)

        max_w = min(6, total_files) if total_files > 0 else 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_w) as executor:
            list(executor.map(_upload_worker, files_to_upload))

        self.after(0, lambda: self.prog_label.configure(text=f"{t('msg_upload_complete')}{round(total_size_bytes/(1024*1024), 2)} MB"))
        self.after(0, lambda: self.enter_bucket(self.current_bucket))
        self.after(0, lambda: messagebox.showinfo(t("msg_success_title"), f"{t('msg_uploaded_count_1')}{total_files}{t('msg_uploaded_count_2')}"))
        self.after(1500, lambda: self.show_progress(False))

if __name__ == "__main__":
    app = S3UniversalApp()
    app.mainloop()