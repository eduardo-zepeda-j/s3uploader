import customtkinter as ctk
import boto3
import os
import sys # <--- NECESARIO PARA COMPILACIÓN
import json
import threading
import csv
import mimetypes
from PIL import Image, ImageTk
from tkinter import filedialog, messagebox, simpledialog
from tkinterdnd2 import TkinterDnD, DND_FILES

ctk.set_appearance_mode("dark")

# --- FUNCIÓN CRÍTICA PARA COMPILACIÓN ---
# Esta función permite encontrar archivos adjuntos (como el icono)
# tanto si corres el .py como si corres el .app compilado.
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class S3UniversalApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        self.title("S3 Uploader - By Eduardo Zepeda - V 0.0.2 ")
        self.geometry("1400x900")
        
        # Cargar Icono (Versión local)
        self.load_app_icon()

        # Cross-platform config path
        self.config_path = os.path.join(os.path.expanduser("~"), ".s3_commander_config.json")
        self.s3 = None
        self.current_bucket = None
        self.current_prefix = "" 
        
        self.init_ui()

        self.load_session()
        
        # Selección múltiple
        self.selected_items = set() # Stores tuple: (full_path, type, name)

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
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")

        ctk.CTkLabel(self.sidebar, text="Configuración AWS\n(Arrastra CSV)", font=("Helvetica", 16, "bold")).pack(pady=20)
        
        self.entry_ak = ctk.CTkEntry(self.sidebar, placeholder_text="Access Key", show="*")
        self.entry_ak.pack(pady=5, padx=10, fill="x")
        self.entry_sk = ctk.CTkEntry(self.sidebar, placeholder_text="Secret Key", show="*")
        self.entry_sk.pack(pady=5, padx=10, fill="x")
        self.entry_rg = ctk.CTkEntry(self.sidebar, placeholder_text="Región (us-east-1)")
        self.entry_rg.pack(pady=5, padx=10, fill="x")

        self.btn_connect = ctk.CTkButton(self.sidebar, text="Conectar / Refrescar", command=self.connect_aws)
        self.btn_connect.pack(pady=15, padx=10)

        ctk.CTkLabel(self.sidebar, text="Clase de Almacenamiento", font=("Helvetica", 14)).pack(pady=(20,5))
        self.storage_menu = ctk.CTkOptionMenu(self.sidebar, values=["STANDARD", "GLACIER_IR", "DEEP_ARCHIVE", "ONEZONE_IA"])
        self.storage_menu.pack(pady=5, padx=10)

        # --- Main View ---
        self.main_view = ctk.CTkFrame(self)
        self.main_view.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        # Navegación Superior
        # Navegación Superior (Breadcrumbs)
        self.nav_frame = ctk.CTkFrame(self.main_view, fg_color="transparent")
        self.nav_frame.pack(fill="x", pady=5)
        
        self.btn_back = ctk.CTkButton(self.nav_frame, text="⬅", width=40, command=self.go_back, fg_color="#333", hover_color="#444")
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

        self.btn_download_sel = ctk.CTkButton(self.actions_frame, text="⬇ Descargar Slc.", command=self.download_selected_items, fg_color="#107C10", hover_color="#0b570b", width=120)
        self.btn_download_sel.pack(side="left", padx=5)

        self.btn_up_files = ctk.CTkButton(self.actions_frame, text="+ Subir Archivos", command=lambda: self.upload_task("files"), fg_color="#2b2b2b", hover_color="#3a3a3a", border_width=1, border_color="#555")
        self.btn_up_files.pack(side="left", padx=5)

        self.btn_up_folder = ctk.CTkButton(self.actions_frame, text="+ Subir Carpeta", command=lambda: self.upload_task("folder"), fg_color="#2b2b2b", hover_color="#3a3a3a", border_width=1, border_color="#555")
        self.btn_up_folder.pack(side="left", padx=5)

        self.btn_new_folder = ctk.CTkButton(self.actions_frame, text="+ Nueva Carpeta", fg_color="#E86E12", hover_color="#C45605", command=self.create_folder_task)
        self.btn_new_folder.pack(side="left", padx=5)

        # Progreso
        self.prog_label = ctk.CTkLabel(self.main_view, text="Listo", font=("Helvetica", 12))
        self.prog_label.pack(pady=2)
        self.prog_bar = ctk.CTkProgressBar(self.main_view, progress_color="#E86E12")
        self.prog_bar.pack(fill="x", padx=20)
        self.prog_bar.set(0)

        # Habilitar Drop de archivos
        self.drop_target_register(DND_FILES)
        self.dnd_bind('<<Drop>>', self.on_drop)

    def on_drop(self, event):
        data = event.data
        pointer_x = self.winfo_pointerx()
        sidebar_right = self.sidebar.winfo_rootx() + self.sidebar.winfo_width()

        paths = self.parse_dropped_files(data)
        if not paths: return

        if pointer_x < sidebar_right:
            if len(paths) >= 1 and paths[0].lower().endswith('.csv'):
                self.load_credentials_from_path(paths[0])
            else:
                messagebox.showinfo("Zona de Configuración", "Arrastra aquí únicamente tu archivo CSV de credenciales.")
        else:
            self.handle_upload_drop(paths)

    def parse_dropped_files(self, data):
        import re
        if data.startswith('{') and data.endswith('}'):
            raw_paths = re.findall(r'\{(?P<path>.*?)\}', data)
            return raw_paths
        else:
            return [data] 

    def load_credentials_from_path(self, file_path):
        try:
            with open(file_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                headers = next(reader, None)
                if not headers: return

                ak_idx = -1
                sk_idx = -1
                for i, h in enumerate(headers):
                    val = h.lower()
                    if "access" in val and "key" in val and "id" in val:
                        ak_idx = i
                    elif "secret" in val and "key" in val:
                        sk_idx = i

                if ak_idx != -1 and sk_idx != -1:
                    row = next(reader, None)
                    if row:
                        self.entry_ak.delete(0, "end")
                        self.entry_ak.insert(0, row[ak_idx].strip())
                        self.entry_sk.delete(0, "end")
                        self.entry_sk.insert(0, row[sk_idx].strip())
                        messagebox.showinfo("Credenciales", "Credenciales cargadas.")
        except Exception as e:
            messagebox.showerror("Error CSV", str(e))

    def handle_upload_drop(self, paths):
        if not self.s3 or not self.current_bucket:
            messagebox.showwarning("Atención", "Conecta y selecciona un Bucket primero.")
            return

        if messagebox.askyesno("Confirmar carga", f"¿Deseas subir {len(paths)} elemento(s)?"):
            threading.Thread(target=self.hilo_upload, args=(paths, "mixed"), daemon=True).start()

    def save_session(self):
        config = {
            "ak": self.entry_ak.get(),
            "sk": self.entry_sk.get(),
            "rg": self.entry_rg.get(),
            "last_bucket": self.current_bucket,
            "last_prefix": self.current_prefix
        }
        with open(self.config_path, "w") as f:
            json.dump(config, f)

    def load_session(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r") as f:
                c = json.load(f)
                self.entry_ak.insert(0, c.get("ak", ""))
                self.entry_sk.insert(0, c.get("sk", ""))
                self.entry_rg.insert(0, c.get("rg", "us-east-1"))
                self.current_bucket = c.get("last_bucket")
                self.current_prefix = c.get("last_prefix", "")

    def connect_aws(self):
        ak = self.entry_ak.get().strip()
        sk = self.entry_sk.get().strip()
        rg = self.entry_rg.get().strip()

        if not ak or not sk: return
        if not rg: rg = "us-east-1"

        try:
            self.s3 = boto3.client('s3', aws_access_key_id=ak, aws_secret_access_key=sk, region_name=rg)
            if self.current_bucket:
                self.enter_bucket(self.current_bucket)
            else:
                self.list_buckets()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def update_breadcrumbs(self):
        # Limpiar breadcrumbs anteriores
        for widget in self.breadcrumbs_frame.winfo_children():
            widget.destroy()

        # Botón "Inicio" (Lista de Buckets)
        btn_home = ctk.CTkButton(self.breadcrumbs_frame, text="🏠 Inicio", width=30, fg_color="transparent", text_color="#AAAAAA", hover_color="#333", command=self.list_buckets)
        btn_home.pack(side="left", padx=2)

        if self.current_bucket:
             # Separador
             ctk.CTkLabel(self.breadcrumbs_frame, text=">", text_color="gray").pack(side="left", padx=2)
             
             # Botón Bucket
             if not self.current_prefix:
                 # Bucket es el actual (activo)
                 btn_bucket = ctk.CTkButton(self.breadcrumbs_frame, text=self.current_bucket, fg_color="#E86E12", text_color="white", hover=False)
             else:
                 # Bucket es un paso previo
                 btn_bucket = ctk.CTkButton(self.breadcrumbs_frame, text=self.current_bucket, fg_color="transparent", text_color="#E86E12", hover_color="#333",
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
                     ctk.CTkLabel(self.breadcrumbs_frame, text=">", text_color="gray").pack(side="left", padx=2)
                     
                     is_last = (i == len(parts) - 1)
                     
                     if is_last:
                         # Carpeta actual (activa) - Sin comando
                         btn_part = ctk.CTkButton(self.breadcrumbs_frame, text=part, fg_color="#4DA6FF", text_color="white", hover=False)
                     else:
                         # Carpeta padre - Navegable
                         def go_path(p=accumulated_path):
                             self.current_prefix = p
                             self.enter_bucket(self.current_bucket)
                         
                         btn_part = ctk.CTkButton(self.breadcrumbs_frame, text=part, fg_color="transparent", text_color="#4DA6FF", hover_color="#333", command=go_path)
                     
                     btn_part.pack(side="left", padx=2)

    def clear_list_frame(self):
        self.grid_idx = 0  # Reset counter
        self.selected_items.clear() # Limpiar selección al cambiar de vista/bucket
        for widget in self.file_list_frame.winfo_children():
            widget.destroy()

    def toggle_selection(self, type, name, full_path):
        item = (full_path, type, name)
        if item in self.selected_items:
            self.selected_items.remove(item)
        else:
            self.selected_items.add(item)

    def list_buckets(self):
        self.current_bucket = None
        self.update_breadcrumbs()
        self.clear_list_frame()
        
        try:
            response = self.s3.list_buckets()
            for b in response['Buckets']:
                self.create_list_item("bucket", b['Name'])
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def enter_bucket(self, bucket_name):
        self.current_bucket = bucket_name
        self.update_breadcrumbs()
        self.clear_list_frame()
        
        lbl = ctk.CTkLabel(self.file_list_frame, text="Cargando...", font=("Helvetica", 20, "bold"))
        lbl.grid(row=0, column=0, columnspan=4, pady=50)
        
        try:
            resp = self.s3.list_objects_v2(Bucket=bucket_name, Prefix=self.current_prefix, Delimiter='/')
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
                        # Detectar extensión para icono
                        _, ext = os.path.splitext(file_name)
                        self.create_list_item("file", file_name, full_path=obj['Key'], size=f"{size_kb} KB", ext=ext)
            
            self.save_session()
        except Exception as e:
            self.list_buckets()

    def copy_link(self, full_path):
        try:
            url = self.s3.generate_presigned_url(
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
                    head = self.s3.head_object(Bucket=self.current_bucket, Key=full_path)
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
                    self.s3.download_file(self.current_bucket, full_path, local_path, Callback=progress_tracker)
                    
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
                        head = self.s3.head_object(Bucket=self.current_bucket, Key=full_path)
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
                     paginator = self.s3.get_paginator('list_objects_v2')
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
                     self.s3.download_file(self.current_bucket, k, local, Callback=tracker)
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

    def create_list_item(self, type, name, full_path=None, size="", ext=""):
        # Calcular posición en Grid
        row = self.grid_idx // self.columns_per_row
        col = self.grid_idx % self.columns_per_row
        self.grid_idx += 1

        # Color de fondo de la tarjeta diferenciado para Buckets
        card_color = ("#2B2B2B", "#333333")
        border_color = "#444"
        if type == "bucket":
            card_color = ("#353535", "#2a2a2a") # Ligeramente más claro/distinto
            border_color = "#E86E12" # Borde naranja sutil para que sea llamativo
            
        # Tarjeta principal
        card = ctk.CTkFrame(self.file_list_frame, corner_radius=15, fg_color=card_color, border_width=1 if type == "bucket" else 1, border_color=border_color)
        card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

        # Checkbox de selección (Top-Left)
        if type in ["file", "folder"]:
            # Usar una variable para trackeo visual si se desea, o simplemente comando directo
            chk = ctk.CTkCheckBox(card, text="", width=20, height=20, corner_radius=5, checkbox_width=18, checkbox_height=18,
                                  command=lambda t=type, n=name, p=full_path: self.toggle_selection(t, n, p))
            chk.place(x=8, y=8)
            # Marcar si ya estaba seleccionado (persistencia simple durante navegación)
            if (full_path, type, name) in self.selected_items:
                chk.select()
        
        # Usar un Frame interno para centrar el contenido perfectamente
        content_frame = ctk.CTkFrame(card, fg_color="transparent")
        content_frame.pack(expand=True, fill="both", padx=5, pady=5)
        
        # Ensure Checkbox is on top
        if type in ["file", "folder"] and 'chk' in locals():
            chk.lift()

        icon = "📄"
        icon_color = "#CCCCCC"
        command = None
        hover_cursor = "arrow"

        # --- Selección de Iconos ---
        if type == "bucket":
            icon = "🪣"
            icon_color = "#E86E12" 
            command = lambda: self.enter_bucket(name)
            hover_cursor = "hand2"
            
        elif type == "folder":
            icon = "📂"
            icon_color = "#4DA6FF"
            command = lambda: self.enter_subfolder(full_path)
            hover_cursor = "hand2"
            
        elif type == "file":
             ext_norm = ext.lower().strip('.') if ext else ""
             
             # Audio
             if ext_norm in ['mp3', 'wav', 'aac', 'flac', 'ogg', 'm4a']:
                 icon = "🎵"
                 icon_color = "#1DB954"
             # Video
             elif ext_norm in ['mp4', 'mov', 'avi', 'mkv', 'webm', 'flv']:
                 icon = "🎬"
                 icon_color = "#FF4500"
             # Imagen
             elif ext_norm in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp']:
                 icon = "🖼️"
                 icon_color = "#FFD700"
             # Documentos
             elif ext_norm in ['pdf']:
                 icon = "📕"
                 icon_color = "#F40F02"
             elif ext_norm in ['doc', 'docx']:
                 icon = "📝"
                 icon_color = "#2B579A"
             elif ext_norm in ['xls', 'xlsx', 'csv']:
                 icon = "📊"
                 icon_color = "#217346"
             elif ext_norm in ['ppt', 'pptx']:
                 icon = "📉"
                 icon_color = "#D24726"
             elif ext_norm in ['txt', 'md', 'py', 'json', 'xml']:
                 icon = "📄"
                 icon_color = "#CCCCCC"
             elif ext_norm in ['zip', 'rar', '7z', 'tar', 'gz']:
                 icon = "📦"
                 icon_color = "#A52A2A"
             else:
                 icon = "📄"
                 icon_color = "#999999"
        
        # --- Icono Grande ---
        font_size = 48
        if type == "bucket": font_size = 56 # Icono más grande para buscar impacto visual

        font_check = ("Segoe UI Emoji", font_size) if os.name == 'nt' else ("Apple Color Emoji", font_size)
        try:
             btn_icon = ctk.CTkButton(content_frame, text=icon, font=("Arial", font_size), fg_color="transparent", hover=False, 
                                      command=command, text_color=icon_color, height=font_size+10)
        except:
             btn_icon = ctk.CTkButton(content_frame, text=icon, font=("Helvetica", font_size), fg_color="transparent", hover=False,
                                      command=command, text_color=icon_color, height=font_size+10)
        
        if hover_cursor == "hand2":
            btn_icon.configure(hover=True, hover_color="#444444")
        
        # Pack para centrar verticalmente, empujando todo al medio
        btn_icon.pack(side="top", pady=(10, 2), expand=True)

        # --- Nombre del Archivo/Carpeta ---
        # Wraplength ajustado
        lbl_name = ctk.CTkLabel(content_frame, text=name, font=("Helvetica", 13, "bold"), wraplength=130, justify="center")
        lbl_name.pack(side="top", pady=(0, 10))

        # --- Footer: Detalles y Acciones (Solo si no es bucket) ---
        if type != "bucket":
            footer = ctk.CTkFrame(card, fg_color="transparent", height=30)
            footer.pack(side="bottom", fill="x", padx=5, pady=(0, 5))
            
            # Si es archivo, mostrar tamaño
            if type == "file":
                 lbl_size = ctk.CTkLabel(footer, text=size, font=("Consolas", 10), text_color="gray")
                 lbl_size.pack(side="top", pady=(0, 2))

            # Botones de acción 
            if self.current_bucket:
                 actions_inner = ctk.CTkFrame(footer, fg_color="transparent")
                 actions_inner.pack(side="bottom", pady=2)

                 btn_del = ctk.CTkButton(actions_inner, text="🗑", width=28, height=28, fg_color="#990000", hover_color="#B30000",
                                         command=lambda: self.request_delete(name, type, full_path), corner_radius=6)
                 btn_del.pack(side="left", padx=3)
                 
                 if type == "file":
                    btn_link = ctk.CTkButton(actions_inner, text="🔗", width=28, height=28, fg_color="#1f538d", hover_color="#14375e",
                                             command=lambda: self.copy_link(full_path), corner_radius=6)
                    btn_link.pack(side="left", padx=3)
                    
                    # Usamos una flecha genérica "⬇" o "▼" que suele tener mejor soporte que el Inbox tray
                    btn_down = ctk.CTkButton(actions_inner, text="⬇", width=28, height=28, fg_color="#107C10", hover_color="#0b570b",
                                             command=lambda: self.download_file(full_path, name), corner_radius=6)
                    btn_down.pack(side="left", padx=3)

    def request_delete(self, name, type, full_path):
        pwd = ctk.CTkInputDialog(text=f"Pass para borrar '{name}':", title="Seguridad").get_input()
        if pwd == "5834":
            if messagebox.askyesno("Confirmar Eliminación", f"¿Estás SEGURO de eliminar definitivamente:\n\n{name}\n\nEsta acción no se puede deshacer?"):
                ak = self.entry_ak.get().strip()
                sk = self.entry_sk.get().strip()
                rg = self.entry_rg.get().strip()
                if not rg: rg = "us-east-1"
                creds = (ak, sk, rg)
                threading.Thread(target=self.perform_delete, args=(full_path, type, creds), daemon=True).start()

    def perform_delete(self, key, type, creds):
        try:
            if type == "folder":
                ak, sk, rg = creds
                s3_resource = boto3.resource('s3', aws_access_key_id=ak, aws_secret_access_key=sk, region_name=rg)
                s3_resource.Bucket(self.current_bucket).objects.filter(Prefix=key).delete()
            else:
                self.s3.delete_object(Bucket=self.current_bucket, Key=key)
            
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
                self.s3.put_object(Bucket=self.current_bucket, Key=full_key)
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
                self.s3.upload_file(local, self.current_bucket, final_key, 
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