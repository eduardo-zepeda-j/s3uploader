import customtkinter as ctk
import os
import sys
import json
import threading
import csv
import queue
import mimetypes
from datetime import datetime, timedelta
import keyring
from PIL import Image, ImageTk
from tkinter import filedialog, messagebox, simpledialog
from tkinterdnd2 import TkinterDnD, DND_FILES

from core.auth_manager import AuthManager
from core.s3_manager import S3Manager
from ui.login_window import LoginWindow
from ui.move_modal import MoveModal
from utils.helpers import resource_path, get_download_dir

FILE_ICONS = [
    (['mp3', 'wav', 'aac', 'flac', 'ogg', 'm4a'], "🎵", ("#107c10", "#1DB954")),
    (['mp4', 'mov', 'avi', 'mkv', 'webm', 'flv'], "🎬", ("#cc3300", "#FF4500")),
    (['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp'], "🖼️", ("#b38b00", "#FFD700")),
    (['pdf'], "📕", ("#cc0000", "#F40F02")),
    (['doc', 'docx'], "📝", ("#1e3b70", "#2B579A")),
    (['xls', 'xlsx', 'csv'], "📊", ("#154c2a", "#217346")),
    (['ppt', 'pptx'], "📉", ("#b33c20", "#D24726")),
    (['txt', 'md', 'py', 'json', 'xml'], "📄", ("#444444", "#CCCCCC")),
    (['zip', 'rar', '7z', 'tar', 'gz'], "📦", ("#800000", "#A52A2A"))
]
EXT_MAP = {ext: (icon, color) for exts, icon, color in FILE_ICONS for ext in exts}

class S3UniversalApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        self.title("S3 Uploader - By Eduardo Zepeda - V 0.0.2 ")
        self.geometry("1400x900")
        self.withdraw()
        
        # Cargar Icono (Versión local)
        self.load_app_icon()

        # Cross-platform config path
        # Reemplazamos configuraciones antiguas por AuthManager
        self.auth_manager = AuthManager()
        self.s3_manager = None

        self.current_bucket = None
        self.current_prefix = "" 
        # UI State persistent path
        self.config_path = os.path.join(os.path.expanduser("~"), ".s3_commander_config.json")
        
        self.view_mode = "grid"
        self.thumbnail_cache = []
        self.delete_password = "5834"
        
        self.load_session()
        self.init_ui()

        # Selección múltiple
        self.selected_items = set() # Stores tuple: (full_path, type, name)
        self.after(100, self.check_login_status)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        import os
        os._exit(0)

    # --- NUEVA VERSIÓN DE CARGA DE ICONO ---
    def load_app_icon(self):
        try:
            # Busca el archivo "s3icono.png" que adjuntaremos al compilar
            icon_path = resource_path("s3icono.png")
            
            if os.path.exists(icon_path):
                image = Image.open(icon_path)
                self.icon_image = ImageTk.PhotoImage(image)
                # Establece el icono de la ventana y del Dock en runtime
                self.iconphoto(True, self.icon_image) 
            else:
                print(f"Advertencia: No se encontró el icono en {icon_path}")
        except Exception as e:
            print(f"Error cargando icono: {e}")

    def init_ui(self):
        # --- Sidebar ---
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=("#E5E7EB", "#0B0C10"))
        self.sidebar.pack(side="left", fill="y")

        ctk.CTkLabel(self.sidebar, text="Mis Repositorios", font=("Helvetica Neue", 20, "bold"), text_color=("#111827", "#F9FAFB")).pack(pady=(30, 10))
        self.sidebar_buckets_frame = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.sidebar_buckets_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.btn_refresh_buckets = ctk.CTkButton(self.sidebar, text="↻ Refrescar", font=("Helvetica Neue", 13, "bold"), fg_color=("#F3F4F6", "#1F2937"), hover_color=("#D1D5DB", "#374151"), text_color=("#374151", "#E5E7EB"), command=self.populate_sidebar_buckets)
        self.btn_refresh_buckets.pack(pady=10, padx=20, fill="x")

        self.btn_change_pass = ctk.CTkButton(self.sidebar, text="🔑 Cambiar PIN de Borrado", font=("Helvetica Neue", 13, "bold"), fg_color="transparent", hover_color=("#D1D5DB", "#1F2937"), text_color=("#374151", "#E5E7EB"), command=self.change_password_task)
        self.btn_change_pass.pack(pady=(0, 10), padx=20, fill="x")

        self.theme_switch = ctk.CTkSwitch(self.sidebar, text="Modo Claro", font=("Helvetica Neue", 13), command=self.toggle_theme)
        self.theme_switch.pack(side="bottom", pady=25)

        self.btn_logout = ctk.CTkButton(self.sidebar, text="🚪 Cerrar Sesión", font=("Helvetica Neue", 14, "bold"), fg_color=("#FEE2E2", "#7F1D1D"), hover_color=("#FECACA", "#991B1B"), text_color=("#991B1B", "#FECACA"), command=self.logout)
        self.btn_logout.pack(side="bottom", pady=10, padx=20, fill="x")

        self.storage_menu = ctk.CTkOptionMenu(self.sidebar, values=["STANDARD", "GLACIER_IR", "DEEP_ARCHIVE", "ONEZONE_IA"], font=("Helvetica Neue", 12), fg_color=("#E5E7EB", "#1F2937"), button_color=("#D1D5DB", "#374151"), text_color=("#111827", "#F9FAFB"))
        self.storage_menu.pack(side="bottom", pady=5, padx=20, fill="x")
        ctk.CTkLabel(self.sidebar, text="Clase de Almacenamiento", font=("Helvetica Neue", 12, "bold"), text_color=("#6B7280", "#9CA3AF")).pack(side="bottom", pady=(15,0))

        # --- Main View ---
        self.main_view = ctk.CTkFrame(self, fg_color=("#FFFFFF", "#1F2937"), corner_radius=0)
        self.main_view.pack(side="right", fill="both", expand=True)

        # Navegación Superior
        # Navegación Superior (Breadcrumbs)
        self.nav_frame = ctk.CTkFrame(self.main_view, fg_color="transparent")
        self.nav_frame.pack(fill="x", pady=5)
        
        self.btn_back = ctk.CTkButton(self.nav_frame, text="⬅", width=40, command=self.go_back, fg_color=("#CCCCCC", "#333333"), hover_color=("#AAAAAA", "#444444"), text_color=("#000000", "#FFFFFF"))
        self.btn_back.pack(side="left", padx=(0, 10))
        
        # Frame scrollable horizontal para los breadcrumbs por si la ruta es muy larga
        self.path_scroll = ctk.CTkScrollableFrame(self.nav_frame, height=40, orientation="horizontal", fg_color="transparent")
        self.path_scroll.pack(side="left", fill="x", expand=True)
        
        # Contenedor interno para los botones
        self.breadcrumbs_frame = ctk.CTkFrame(self.path_scroll, fg_color="transparent")
        self.breadcrumbs_frame.pack(side="left", fill="y")

        # Lista de Objetos/Buckets (Grid)
        self.file_list_frame = ctk.CTkScrollableFrame(self.main_view, fg_color="transparent")
        self.file_list_frame.pack(fill="both", expand=True, pady=10)
        
        # Configurar columnas del grid para que se expandan
        self.columns_per_row = 5
        for i in range(self.columns_per_row):
             self.file_list_frame.grid_columnconfigure(i, weight=1)

        # Botones de Acción
        self.actions_frame = ctk.CTkFrame(self.main_view, fg_color="transparent")
        self.actions_frame.pack(fill="x", pady=5)

        self.btn_download_sel = ctk.CTkButton(self.actions_frame, text="⬇ Descargar Slc.", font=("Helvetica Neue", 13, "bold"), command=self.download_selected_items, fg_color=("#D1FAE5", "#064E3B"), hover_color=("#A7F3D0", "#065F46"), text_color=("#065F46", "#34D399"), width=130)
        self.btn_download_sel.pack(side="left", padx=8)

        self.btn_move_sel = ctk.CTkButton(self.actions_frame, text="🚚 Mover Slc.", font=("Helvetica Neue", 13, "bold"), command=self.move_selected_items, fg_color=("#DBEAFE", "#1E3A8A"), hover_color=("#BFDBFE", "#1E40AF"), text_color=("#1E40AF", "#60A5FA"), width=110)
        self.btn_move_sel.pack(side="left", padx=8)

        self.btn_up_files = ctk.CTkButton(self.actions_frame, text="+ Subir Archivos", font=("Helvetica Neue", 13, "bold"), command=lambda: self.upload_task("files"), fg_color=("#F3F4F6", "#374151"), hover_color=("#D1D5DB", "#4B5563"), text_color=("#111827", "#F9FAFB"))
        self.btn_up_files.pack(side="left", padx=8)

        self.btn_up_folder = ctk.CTkButton(self.actions_frame, text="+ Subir Carpeta", font=("Helvetica Neue", 13, "bold"), command=lambda: self.upload_task("folder"), fg_color=("#F3F4F6", "#374151"), hover_color=("#D1D5DB", "#4B5563"), text_color=("#111827", "#F9FAFB"))
        self.btn_up_folder.pack(side="left", padx=8)

        self.btn_new_folder = ctk.CTkButton(self.actions_frame, text="+ Nueva Carpeta", font=("Helvetica Neue", 13, "bold"), fg_color=("#FEF3C7", "#78350F"), hover_color=("#FDE68A", "#92400E"), text_color=("#92400E", "#FDE68A"), command=self.create_folder_task)
        self.btn_new_folder.pack(side="left", padx=8)

        self.btn_view_mode = ctk.CTkButton(self.actions_frame, text="Visión: Cuadrícula", font=("Helvetica Neue", 13, "bold"), fg_color=("#F3F4F6", "#374151"), hover_color=("#D1D5DB", "#4B5563"), command=self.toggle_view_mode, text_color=("#111827", "#F9FAFB"))
        self.btn_view_mode.pack(side="right", padx=15)

        # Progreso
        self.prog_label = ctk.CTkLabel(self.main_view, text="Listo", font=("Helvetica Neue", 12))
        self.prog_label.pack(pady=4)
        self.prog_bar = ctk.CTkProgressBar(self.main_view, progress_color="#F59E0B", fg_color=("#E5E7EB", "#374151"), height=8)
        self.prog_bar.pack(fill="x", padx=30, pady=(0, 10))
        self.prog_bar.set(0)

        # Habilitar Drop de archivos
        self.drop_target_register(DND_FILES)
        self.dnd_bind('<<Drop>>', self.on_drop)

    def on_drop(self, event):
        data = event.data
        paths = self.parse_dropped_files(data)
        if not paths: return
        self.handle_upload_drop(paths)

    def parse_dropped_files(self, data):
        import re
        if data.startswith('{') and data.endswith('}'):
            raw_paths = re.findall(r'\{(?P<path>.*?)\}', data)
            return raw_paths
        else:
            return [data] 

    def handle_upload_drop(self, paths):
        if not self.s3_manager or not self.current_bucket:
            messagebox.showwarning("Atención", "Conecta y selecciona un Bucket primero.")
            return

        if messagebox.askyesno("Confirmar carga", f"¿Deseas subir {len(paths)} elemento(s)?"):
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
        config["delete_password"] = self.delete_password
        with open(self.config_path, "w") as f:
            json.dump(config, f)

    def load_session(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    c = json.load(f)
                    self.current_bucket = c.get("last_bucket")
                    self.current_prefix = c.get("last_prefix", "")
                    self.delete_password = c.get("delete_password", "5834")
            except: pass



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
                btn = ctk.CTkButton(self.sidebar_buckets_frame, text="🪣 " + bname, fg_color="transparent", 
                                    text_color=("#4B5563", "#AAAAAA"), hover_color=("#D1D5DB", "#333333"), anchor="w", command=cmd)
                btn.pack(fill="x", pady=2)
        except Exception as e:
            print("Error listando buckets:", e)

    def enter_bucket_from_sidebar(self, bucket_name):
        self.current_prefix = ""
        self.enter_bucket(bucket_name)

    def update_breadcrumbs(self):
        # Limpiar breadcrumbs anteriores
        for widget in self.breadcrumbs_frame.winfo_children():
            widget.destroy()

        # Botón "Inicio" (Lista de Buckets)
        btn_home = ctk.CTkButton(self.breadcrumbs_frame, text="🏠 Inicio", width=30, fg_color="transparent", text_color=("#4B5563", "#AAAAAA"), hover_color=("#E5E7EB", "#333333"), command=self.list_buckets)
        btn_home.pack(side="left", padx=2)

        if self.current_bucket:
             # Separador
             ctk.CTkLabel(self.breadcrumbs_frame, text=">", text_color=("#6B7280", "gray")).pack(side="left", padx=2)
             
             # Botón Bucket
             if not self.current_prefix:
                 # Bucket es el actual (activo)
                 btn_bucket = ctk.CTkButton(self.breadcrumbs_frame, text=self.current_bucket, fg_color="#E86E12", text_color="white", hover=False)
             else:
                 # Bucket es un paso previo
                 btn_bucket = ctk.CTkButton(self.breadcrumbs_frame, text=self.current_bucket, fg_color="transparent", text_color=("#C45605", "#E86E12"), hover_color=("#D1D5DB", "#333333"),
                                            command=lambda: self.enter_bucket(self.current_bucket))
                 
                 # Resetear prefix temporalmente para navegar al root del bucket si se da click
                 # Pero cuidado, el lambda captura variable, así que mejor usar helper
                 def go_bucket_root(b=self.current_bucket):
                     self.current_prefix = ""
                     self.enter_bucket(b)
                 btn_bucket.configure(command=go_bucket_root)

             btn_bucket.pack(side="left", padx=2)

             # Procesar carpetas del prefix
             if self.current_prefix:
                 parts = [p for p in self.current_prefix.split('/') if p]
                 accumulated_path = ""
                 
                 for i, part in enumerate(parts):
                     accumulated_path += part + "/"
                     ctk.CTkLabel(self.breadcrumbs_frame, text=">", text_color=("#6B7280", "gray")).pack(side="left", padx=2)
                     
                     is_last = (i == len(parts) - 1)
                     
                     if is_last:
                         # Carpeta actual (activa) - Sin comando
                         btn_part = ctk.CTkButton(self.breadcrumbs_frame, text=part, fg_color=("#0066CC", "#4DA6FF"), text_color="white", hover=False)
                     else:
                         # Carpeta padre - Navegable
                         def go_path(p=accumulated_path):
                             self.current_prefix = p
                             self.enter_bucket(self.current_bucket)
                         
                         btn_part = ctk.CTkButton(self.breadcrumbs_frame, text=part, fg_color="transparent", text_color=("#0066CC", "#4DA6FF"), hover_color=("#D1D5DB", "#333333"), command=go_path)
                     
                     btn_part.pack(side="left", padx=2)

    def toggle_selection(self, item_type, name, full_path):
        item = (full_path, item_type, name)
        if item in self.selected_items:
            self.selected_items.remove(item)
        else:
            self.selected_items.add(item)

    def clear_list_frame(self):
        self.grid_idx = 0  # Reset counter
        self.selected_items.clear() # Limpiar selección al cambiar de vista/bucket
        self.thumbnail_cache.clear()
        for widget in self.file_list_frame.winfo_children():
            widget.destroy()

    def toggle_view_mode(self):
        if self.view_mode == "grid":
            self.view_mode = "list"
            self.btn_view_mode.configure(text="Visión: Lista")
        else:
            self.view_mode = "grid"
            self.btn_view_mode.configure(text="Visión: Cuadrícula")
        if self.current_bucket:
            self.enter_bucket(self.current_bucket)

    def logout(self):
        self.auth_manager.clear_session()
        self.current_bucket = None
        self.s3_manager = None
        for widget in getattr(self, 'sidebar_buckets_frame', ctk.CTkFrame(self)).winfo_children(): widget.destroy()
        for widget in getattr(self, 'file_list_frame', ctk.CTkFrame(self)).winfo_children(): widget.destroy()
        self.withdraw()
        LoginWindow(self, self.on_login_success)

    def change_password_task(self):
        curr_pwd = ctk.CTkInputDialog(text="Ingresa el PIN actual:", title="Seguridad").get_input()
        if curr_pwd == self.delete_password:
            new_pwd = ctk.CTkInputDialog(text="Ingresa el NUEVO PIN:", title="Nuevo PIN").get_input()
            if new_pwd:
                self.delete_password = new_pwd
                self.save_session()
                messagebox.showinfo("Éxito", "PIN actualizado correctamente.")
        elif curr_pwd is not None:
            messagebox.showerror("Error", "PIN actual incorrecto.")

    def list_buckets(self):
        self.current_bucket = None
        self.update_breadcrumbs()
        self.clear_list_frame()
        self.populate_sidebar_buckets()
        
        try:
            response = self.s3_manager.client.list_buckets()
            for b in response['Buckets']:
                self.create_list_item("bucket", b['Name'])
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def enter_bucket(self, bucket_name):
        if self.current_bucket != bucket_name:
            self.current_prefix = ""
        self.current_bucket = bucket_name
        self.update_breadcrumbs()
        self.clear_list_frame()
        
        lbl = ctk.CTkLabel(self.file_list_frame, text="Cargando...", font=("Helvetica", 20, "bold"))
        lbl.grid(row=0, column=0, columnspan=4, pady=50)
        
        try:
            resp = self.s3_manager.client.list_objects_v2(Bucket=bucket_name, Prefix=self.current_prefix, Delimiter='/')
            lbl.destroy()
            
            if 'CommonPrefixes' in resp:
                for cp in resp['CommonPrefixes']:
                    folder_name = cp['Prefix'].rstrip('/').split('/')[-1]
                    self.create_list_item("folder", folder_name, full_path=cp['Prefix'])
            
            if 'Contents' in resp:
                for obj in resp['Contents']:
                    if obj['Key'] != self.current_prefix:
                        file_name = obj['Key'].split('/')[-1]
                        size_kb = round(obj['Size'] / 1024, 2)
                        _, ext = os.path.splitext(file_name)
                        last_mod = obj.get('LastModified')
                        date_str = last_mod.strftime("%Y-%m-%d %H:%M") if last_mod else ""
                        self.create_list_item("file", file_name, full_path=obj['Key'], size=f"{size_kb} KB", ext=ext, date=date_str)
            
            self.save_session()
        except Exception as e:
            self.list_buckets()

    def copy_link(self, full_path):
        try:
            url = self.s3_manager.client.generate_presigned_url(
                ClientMethod='get_object',
                Params={'Bucket': self.current_bucket, 'Key': full_path}
            )
            static_url = url.split('?')[0]
            # Reemplazar %20 por + para formato web de AWS
            web_friendly_url = static_url.replace("%20", "+")
            
            self.clipboard_clear()
            self.clipboard_append(web_friendly_url)
            self.update()
            
            self.prog_label.configure(text=f"Enlace Web copiado: {os.path.basename(full_path)}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo obtener el enlace: {str(e)}")

    def _get_download_dir(self):
        # Obtener carpeta de Descargas del sistema de forma robusta
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
            # 1. Intentar usar xdg-user-dir
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
            
            # Evitar sobreescritura silenciosa (opcional, pero buena práctica)
            if os.path.exists(local_path):
                base, ext = os.path.splitext(local_path)
                counter = 1
                while os.path.exists(local_path):
                    local_path = f"{base}_{counter}{ext}"
                    counter += 1
            
            def perform_download():
                self.after(0, lambda: self.prog_label.configure(text=f"Iniciando descarga de {file_name}..."))
                try:
                    # 1. Obtener tamaño total para calcular porcentaje
                    head = self.s3_manager.client.head_object(Bucket=self.current_bucket, Key=full_path)
                    total_bytes = head.get('ContentLength', 0)

                    # 2. Clase Callback
                    class DownloadProgress(object):
                        def __init__(self, total_size, update_ui_callback):
                            self._total = total_size
                            self._seen_so_far = 0
                            self._lock = threading.Lock()
                            self._update_ui = update_ui_callback

                        def __call__(self, bytes_amount):
                            with self._lock:
                                self._seen_so_far += bytes_amount
                                pct = 0.0
                                if self._total > 0:
                                    pct = self._seen_so_far / self._total
                                self._update_ui(pct, self._seen_so_far)

                    def update_ui_download(pct, seen):
                         self.prog_bar.set(pct)
                         mb_seen = round(seen / (1024 * 1024), 2)
                         mb_total = round(total_bytes / (1024 * 1024), 2)
                         self.prog_label.configure(text=f"Descargando: {int(pct*100)}% ({mb_seen} MB / {mb_total} MB)")

                    progress_tracker = DownloadProgress(total_bytes, lambda p, s: self.after(0, update_ui_download, p, s))

                    # 3. Descargar con Callback
                    self.s3_manager.client.download_file(self.current_bucket, full_path, local_path, Callback=progress_tracker)
                    
                    self.after(0, lambda: messagebox.showinfo("Descarga Exitosa", f"Archivo guardado en:\n{local_path}"))
                    self.after(0, lambda: self.prog_label.configure(text="Descarga compleada"))
                    self.after(0, lambda: self.prog_bar.set(0))
                except Exception as e_inner:
                    # Capture the error string immediately to avoid closure scoping issues
                    err_msg = str(e_inner)
                    self.after(0, lambda m=err_msg: messagebox.showerror("Error Descarga", m))
                    self.after(0, lambda: self.prog_label.configure(text="Error en descarga"))

            threading.Thread(target=perform_download, daemon=True).start()
            
        except Exception as e:
            messagebox.showerror("Error", f"Fallo al iniciar descarga: {str(e)}")

    def download_selected_items(self):
        if not self.selected_items:
            messagebox.showwarning("Selección vacía", "Selecciona al menos un archivo o carpeta.")
            return

        # Destino automático: Carpeta de descargas
        dest_dir = self._get_download_dir()
        if not dest_dir: 
             messagebox.showerror("Error", "No se pudo detectar carpeta de descargas.")
             return

        threading.Thread(target=self.hilo_bulk_download, args=(dest_dir,), daemon=True).start()

    def hilo_bulk_download(self, dest_dir):
        # 1. Resolver todos los items a descargar (aplanar carpetas)
        items_to_process = [] # Lista de (s3_key, local_path_abs, s3_size)
        total_bytes = 0

        self.after(0, lambda: self.prog_label.configure(text="Calculando tamaño total..."))

        try:
             # Copia de seguridad de items seleccionados
             selection = list(self.selected_items)
             
             for (full_path, type, name) in selection:
                 if type == "file":
                     # Obtener tamaño
                     try:
                        head = self.s3_manager.client.head_object(Bucket=self.current_bucket, Key=full_path)
                        sz = head.get('ContentLength', 0)
                        local_tgt = os.path.join(dest_dir, name)
                        # Manejo de duplicados en root
                        base, ext = os.path.splitext(local_tgt)
                        c_dup = 1
                        while os.path.exists(local_tgt):
                             local_tgt = f"{base}_{c_dup}{ext}"
                             c_dup += 1
                        
                        items_to_process.append((full_path, local_tgt, sz))
                        total_bytes += sz
                     except: pass
                 
                 elif type == "folder":
                     # Listar recursivo
                     paginator = self.s3_manager.client.get_paginator('list_objects_v2')
                     # La carpeta destino local será dest_dir/nombre_carpeta
                     local_folder_root = os.path.join(dest_dir, name)
                     if not os.path.exists(local_folder_root):
                         os.makedirs(local_folder_root, exist_ok=True)
                     
                     for page in paginator.paginate(Bucket=self.current_bucket, Prefix=full_path):
                         if 'Contents' in page:
                             for obj in page['Contents']:
                                 k = obj['Key']
                                 # Skip si es la carpeta misma (marcador de 0 bytes)
                                 if k == full_path: continue
                                 
                                 sz = obj['Size']
                                 # Calcular ruta relativa desde el full_path seleccionado
                                 rel_path = os.path.relpath(k, full_path)
                                 local_tgt = os.path.join(local_folder_root, rel_path)
                                 
                                 # Crear subdirectorios si hacen falta
                                 ldir = os.path.dirname(local_tgt)
                                 if not os.path.exists(ldir):
                                     os.makedirs(ldir, exist_ok=True)
                                     
                                 items_to_process.append((k, local_tgt, sz))
                                 total_bytes += sz

             # 2. Configurar Progreso
             class BulkDownloadProgress(object):
                def __init__(self, total_size, update_ui_callback):
                    self._total = total_size
                    self._seen_so_far = 0
                    self._lock = threading.Lock()
                    self._update_ui = update_ui_callback

                def __call__(self, bytes_amount):
                    with self._lock:
                        self._seen_so_far += bytes_amount
                        pct = 0.0
                        if self._total > 0:
                            pct = self._seen_so_far / self._total
                        self._update_ui(pct, self._seen_so_far)

             def update_ui_bulk(pct, seen):
                 self.prog_bar.set(pct)
                 mb_seen = round(seen / (1024 * 1024), 2)
                 mb_total = round(total_bytes / (1024 * 1024), 2)
                 self.prog_label.configure(text=f"Descarga Total: {int(pct*100)}% ({mb_seen} MB / {mb_total} MB)")

             tracker = BulkDownloadProgress(total_bytes, lambda p, s: self.after(0, update_ui_bulk, p, s))
             
             # 3. Ejecutar Descargas
             for i, (k, local, sz) in enumerate(items_to_process):
                 # self.after(0, lambda m=f"Descargando {os.path.basename(k)}...": self.prog_label.configure(text=m)) # Opcional: mostrar archivo actual
                 try:
                     self.s3_manager.client.download_file(self.current_bucket, k, local, Callback=tracker)
                 except Exception as err:
                     print(f"Error {k}: {err}")
            
             self.after(0, lambda: messagebox.showinfo("Descarga Masiva", f"Se descargaron {len(items_to_process)} archivos exitosamente."))
             self.after(0, lambda: self.prog_label.configure(text="Descarga masiva completada"))
             self.after(0, lambda: self.prog_bar.set(0))
             # Limpiar selección
             self.selection_clear_ui()

        except Exception as e:
            msg = str(e)
            self.after(0, lambda: messagebox.showerror("Error Bulk", msg))

    def selection_clear_ui(self):
        self.selected_items.clear()
        # Refrescar vista para quitar checks (o simplemente iterar widgets, pero refresh es mas limpio)
        self.after(0, lambda: self.enter_bucket(self.current_bucket))

    def toggle_theme(self):
        if self.theme_switch.get() == 1:
            ctk.set_appearance_mode("light")
        else:
            ctk.set_appearance_mode("dark")

    def create_list_item(self, type, name, full_path=None, size="", ext="", date=""):
        row = self.grid_idx // self.columns_per_row
        col = self.grid_idx % self.columns_per_row
        self.grid_idx += 1

        card_color = ("#FFF7ED", "#451A03") if type == "bucket" else (("#EFF6FF", "#172554") if type == "folder" else ("#F3F4F6", "#2A374A"))
        border_color = ("#FDE68A", "#78350F") if type == "bucket" else (("#BFDBFE", "#1E3A8A") if type == "folder" else ("#D1D5DB", "#374151"))
            
        card = ctk.CTkFrame(self.file_list_frame, corner_radius=12, fg_color=card_color, border_width=1, border_color=border_color)
        
        if self.view_mode == "list":
            card.grid(row=self.grid_idx, column=0, columnspan=self.columns_per_row, padx=8, pady=2, sticky="ew")
        else:
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

        content_frame = ctk.CTkFrame(card, fg_color="transparent")
        
        if type in ["file", "folder"]:
            chk = ctk.CTkCheckBox(content_frame if self.view_mode == "list" else card, text="", width=20, height=20, corner_radius=5, checkbox_width=18, checkbox_height=18,
                                  command=lambda t=type, n=name, p=full_path: self.toggle_selection(t, n, p))
            if self.view_mode == "list":
                chk.pack(side="left", padx=(0, 10))
            else:
                chk.place(x=8, y=8)
            if (full_path, type, name) in self.selected_items:
                chk.select()
        
        if self.view_mode == "list":
            content_frame.pack(expand=True, fill="x", padx=10, pady=5)
        else:
            content_frame.pack(expand=True, fill="both", padx=5, pady=5)
            if type in ["file", "folder"] and 'chk' in locals():
                chk.lift()

        icon = "📄"
        icon_color = ("#666666", "#CCCCCC")
        command = None
        hover_cursor = "arrow"

        if type == "bucket":
            icon = "🪣"
            icon_color = ("#cc5500", "#E86E12") 
            command = lambda: self.enter_bucket(name)
            hover_cursor = "hand2"
            
        elif type == "folder":
            icon = "📂"
            icon_color = ("#0066cc", "#4DA6FF")
            command = lambda: self.enter_subfolder(full_path)
            hover_cursor = "hand2"
            
        elif type == "file":
             ext_norm = ext.lower().strip('.') if ext else ""
             icon, icon_color = EXT_MAP.get(ext_norm, ("📄", ("#666666", "#999999")))
        
        font_size = 24 if self.view_mode == "list" else (56 if type == "bucket" else 48)

        try:
             btn_icon = ctk.CTkButton(content_frame, text=icon, font=("Arial", font_size), fg_color="transparent", hover=False, 
                                      command=command, text_color=icon_color, height=font_size+5, width=font_size+5)
        except:
             btn_icon = ctk.CTkButton(content_frame, text=icon, font=("Helvetica", font_size), fg_color="transparent", hover=False,
                                      command=command, text_color=icon_color, height=font_size+5, width=font_size+5)
        
        if hover_cursor == "hand2":
            btn_icon.configure(hover=True, hover_color="#444444")
        
        if self.view_mode == "list":
            btn_icon.pack(side="left", padx=(0, 15))
            lbl_name = ctk.CTkLabel(content_frame, text=name, font=("Helvetica Neue", 14, "bold"), text_color=("#111827", "#F9FAFB"), anchor="w", justify="left")
            lbl_name.pack(side="left", fill="x", expand=True)
            
            if type != "bucket":
                lbl_date = ctk.CTkLabel(content_frame, text=date, font=("Andale Mono", 12), text_color=("#6B7280", "#9CA3AF"), width=140, anchor="e")
                lbl_date.pack(side="left", padx=15)
                if type == "file":
                    lbl_size = ctk.CTkLabel(content_frame, text=size, font=("Andale Mono", 12, "bold"), text_color=("#4B5563", "#D1D5DB"), width=90, anchor="e")
                    lbl_size.pack(side="left", padx=15)
                actions_inner = ctk.CTkFrame(content_frame, fg_color="transparent")
                actions_inner.pack(side="right", padx=10)
                
                btn_move = ctk.CTkButton(actions_inner, text="🚚", width=30, fg_color="transparent", text_color="#107C10", hover_color="#333", command=lambda p=full_path, n=name: self.open_move_modal([(p, type, n)]))
                btn_move.pack(side="left", padx=2)
                
                btn_rename = ctk.CTkButton(actions_inner, text="✏️", width=30, fg_color="transparent", text_color="#107C10", hover_color="#333", command=lambda p=full_path, n=name: self.rename_task(p, type, n))
                btn_rename.pack(side="left", padx=2)
        else:
            btn_icon.pack(side="top", pady=(15, 5), expand=True)
            lbl_name = ctk.CTkLabel(content_frame, text=name, font=("Helvetica Neue", 13, "bold"), text_color=("#111827", "#F9FAFB"), wraplength=140, justify="center")
            lbl_name.pack(side="top", pady=(0, 10))
            
            if type != "bucket":
                footer = ctk.CTkFrame(card, fg_color="transparent", height=35)
                footer.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
                if type == "file":
                     lbl_size = ctk.CTkLabel(footer, text=size, font=("Andale Mono", 11, "bold"), text_color=("#4B5563", "#D1D5DB"))
                     lbl_size.pack(side="top", pady=(0, 4))
                actions_inner = ctk.CTkFrame(footer, fg_color="transparent")
                actions_inner.pack(side="bottom", pady=4)
                


        if type != "bucket":
            if self.current_bucket:
                btn_del = ctk.CTkButton(actions_inner, text="🗑", width=28, height=28, fg_color="#990000", hover_color="#B30000",
                                        command=lambda: self.request_delete(name, type, full_path), corner_radius=6)
                btn_del.pack(side="right", padx=3)
                
                btn_ren = ctk.CTkButton(actions_inner, text="✏️", width=28, height=28, fg_color="#E86E12", hover_color="#C45605",
                                        command=lambda: self.request_rename(name, type, full_path), corner_radius=6)
                btn_ren.pack(side="right", padx=3)
                
                if type == "file":
                    btn_down = ctk.CTkButton(actions_inner, text="⬇", width=28, height=28, fg_color="#107C10", hover_color="#0b570b",
                                             command=lambda: self.download_file(full_path, name), corner_radius=6)
                    btn_down.pack(side="right", padx=3)
                    
                    btn_link = ctk.CTkButton(actions_inner, text="🔗", width=28, height=28, fg_color="#1f538d", hover_color="#14375e",
                                             command=lambda: self.copy_link(full_path), corner_radius=6)
                    btn_link.pack(side="right", padx=3)

    def open_move_modal(self, items_to_move):
        if not items_to_move:
            messagebox.showwarning("Aviso", "No hay elementos para mover.")
            return
        MoveModal(self, self.s3_manager, items_to_move, self.current_bucket, self.current_prefix, self.execute_move)

    def move_selected_items(self):
        self.open_move_modal(self.selected_items)

    def execute_move(self, items, tgt_bucket, tgt_prefix):
        self.prog_bar.set(0)
        self.prog_label.configure(text=f"Moviendo {len(items)} ítems...")
        self.prog_bar.configure(mode="indeterminate")
        self.prog_bar.start()
        
        # Disable buttons temporarily
        self.btn_move_sel.configure(state="disabled")
        
        threading.Thread(target=self.hilo_bulk_move, args=(items, tgt_bucket, tgt_prefix), daemon=True).start()

    def hilo_bulk_move(self, items, tgt_bucket, tgt_prefix):
        try:
            for item in items:
                src_path, item_type, current_name = item
                new_key = tgt_prefix + current_name
                
                if item_type == "folder":
                    if not new_key.endswith('/'): new_key += '/'
                    self.s3_manager.move_folder(self.current_bucket, src_path, tgt_bucket, new_key)
                else:
                    self.s3_manager.move_object(self.current_bucket, src_path, tgt_bucket, new_key)
            
            # Reset selection and refresh UI
            self.selected_items.clear()
            self.after(0, lambda: self.enter_bucket(self.current_bucket))
            self.after(0, lambda: messagebox.showinfo("Mover Completo", f"Los objetos fueron movidos exitosamente a {tgt_bucket}/{tgt_prefix}."))
        except Exception as e:
            self.after(0, lambda err=e: messagebox.showerror("Error al mover", str(err)))
        finally:
            self.after(0, self.prog_bar.stop)
            self.after(0, lambda: self.prog_bar.configure(mode="determinate"))
            self.after(0, lambda: self.prog_label.configure(text="Listo"))
            self.after(0, lambda: self.btn_move_sel.configure(state="normal"))

    def request_rename(self, name, type, full_path):
        import threading
        target_bucket = self.current_bucket
        target_prefix = self.current_prefix
        if type == "file":
            import os
            base_name, ext = os.path.splitext(name)
            new_base = ctk.CTkInputDialog(text=f"Nuevo nombre para '{base_name}'\n(La extensión {ext} se mantendrá):", title="Renombrar").get_input()
            if new_base and new_base != base_name:
                new_name = new_base + ext
                threading.Thread(target=self.perform_rename, args=(name, new_name, type, full_path, target_bucket, target_prefix), daemon=True).start()
        else:
            new_name = ctk.CTkInputDialog(text=f"Nuevo nombre de carpeta para '{name}':", title="Renombrar").get_input()
            if new_name and new_name != name:
                threading.Thread(target=self.perform_rename, args=(name, new_name, type, full_path, target_bucket, target_prefix), daemon=True).start()

    def perform_rename(self, old_name, new_name, type, full_path, target_bucket, target_prefix):
        self.after(0, lambda: self.prog_label.configure(text=f"Renombrando '{old_name}' a '{new_name}'..."))
        self.after(0, lambda: self.prog_bar.configure(mode="indeterminate"))
        self.after(0, lambda: self.prog_bar.start())
        try:
            if type == "folder":
                parent = "/".join(full_path.strip('/').split('/')[:-1])
                parent = parent + "/" if parent else ""
                new_key_base = parent + new_name + "/"
                
                paginator = self.s3_manager.client.get_paginator('list_objects_v2')
                for page in paginator.paginate(Bucket=target_bucket, Prefix=full_path):
                    if 'Contents' in page:
                        for obj in page['Contents']:
                            old_obj_key = obj['Key']
                            new_obj_key = old_obj_key.replace(full_path, new_key_base, 1)
                            self.s3_manager.client.copy_object(Bucket=target_bucket, CopySource={'Bucket': target_bucket, 'Key': old_obj_key}, Key=new_obj_key)
                            self.s3_manager.client.delete_object(Bucket=target_bucket, Key=old_obj_key)
            else:
                parent = "/".join(full_path.split('/')[:-1])
                parent = parent + "/" if parent else ""
                new_key = parent + new_name
                self.s3_manager.client.copy_object(Bucket=target_bucket, CopySource={'Bucket': target_bucket, 'Key': full_path}, Key=new_key)
                self.s3_manager.client.delete_object(Bucket=target_bucket, Key=full_path)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error Renombrando", str(e)))
        finally:
            self.after(0, lambda: self.prog_bar.stop())
            self.after(0, lambda: self.prog_bar.configure(mode="determinate"))
            self.after(0, lambda: self.prog_label.configure(text="Listo"))
            self.after(0, lambda: self.prog_bar.set(0))
            if self.current_bucket == target_bucket and self.current_prefix == target_prefix:
                self.after(0, lambda: self.enter_bucket(self.current_bucket))

    def request_delete(self, name, type, full_path):
        pwd = ctk.CTkInputDialog(text=f"Pass para borrar '{name}':", title="Seguridad").get_input()
        if pwd == self.delete_password:
            if messagebox.askyesno("Confirmar Eliminación", f"¿Estás SEGURO de eliminar definitivamente:\n\n{name}\n\nEsta acción no se puede deshacer?"):
                target_bucket = self.current_bucket
                target_prefix = self.current_prefix
                import threading
                threading.Thread(target=self.perform_delete, args=(full_path, type, target_bucket, target_prefix), daemon=True).start()
        elif pwd is not None:
            messagebox.showerror("Error de Seguridad", "La contraseña ingresada es incorrecta")

    def perform_delete(self, key, type, target_bucket, target_prefix):
        try:
            if type == "folder":
                self.s3_manager.delete_folder(target_bucket, key)
            else:
                self.s3_manager.delete_file(target_bucket, key)
            
            if self.current_bucket == target_bucket and self.current_prefix == target_prefix:
                self.after(0, lambda: self.enter_bucket(self.current_bucket))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))

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
        name = ctk.CTkInputDialog(text="Nombre:", title="Nueva Carpeta").get_input()
        if name:
            full_key = self.current_prefix + name.strip().replace("/", "") + "/"
            try:
                self.s3_manager.client.put_object(Bucket=self.current_bucket, Key=full_key)
                self.enter_bucket(self.current_bucket)
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def upload_task(self, type, paths_arg=None):
        if not self.current_bucket: return
        
        if type == "files": paths = filedialog.askopenfilenames()
        elif type == "folder": paths = [filedialog.askdirectory()]
        else: paths = paths_arg
            
        if paths:
           if isinstance(paths, str): paths = [paths]
           threading.Thread(target=self.hilo_upload, args=(paths, type), daemon=True).start()

    def hilo_upload(self, paths, type):
        if isinstance(paths, tuple): paths = list(paths)
        storage = self.storage_menu.get()
        files_to_upload = []
        
        # 1. Recolectar archivos y calcular tamaño total
        total_size_bytes = 0
        for p in paths:
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

        # 2. Callback para seguimiento
        class ProgressPercentage(object):
            def __init__(self, total_size, update_ui_callback):
                self._total = total_size
                self._seen_so_far = 0
                self._lock = threading.Lock()
                self._update_ui = update_ui_callback

            def __call__(self, bytes_amount):
                with self._lock:
                    self._seen_so_far += bytes_amount
                    # Evitar división por cero
                    if self._total > 0:
                        percentage = self._seen_so_far / self._total
                    else:
                        percentage = 1.0
                    self._update_ui(percentage, self._seen_so_far)

        def update_prog_bar(pct, seen):
            # Actualizar barra y etiqueta
            self.prog_bar.set(pct)
            mb_seen = round(seen / (1024 * 1024), 2)
            mb_total = round(total_size_bytes / (1024 * 1024), 2)
            self.prog_label.configure(text=f"Subiendo... {int(pct*100)}% ({mb_seen} MB / {mb_total} MB)")

        progress_tracker = ProgressPercentage(total_size_bytes, lambda p, s: self.after(0, update_prog_bar, p, s))

        # 3. Subir
        total_files = len(files_to_upload)
        for i, (local, s3_key, fsize) in enumerate(files_to_upload):
            final_key = self.current_prefix + s3_key
            
            # Content-Type
            content_type, _ = mimetypes.guess_type(local)
            if content_type is None: content_type = 'application/octet-stream'

            try:
                self.s3_manager.client.upload_file(local, self.current_bucket, final_key, 
                                   ExtraArgs={'StorageClass': storage, 'ContentType': content_type},
                                   Callback=progress_tracker)
            except Exception as e:
                print(f"Error subiendo {s3_key}: {e}")

        self.after(0, lambda: self.prog_label.configure(text=f"¡Carga completa! Total: {round(total_size_bytes/(1024*1024), 2)} MB"))
        self.after(0, lambda: self.enter_bucket(self.current_bucket))
        self.after(0, lambda: messagebox.showinfo("Éxito", f"Se subieron {total_files} elementos exitosamente."))

if __name__ == "__main__":
    app = S3UniversalApp()
    app.mainloop()