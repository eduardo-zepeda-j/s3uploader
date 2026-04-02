import os
import sys

def resource_path(relative_path):
    """
    Permite encontrar archivos adjuntos tanto en desarrollo local como en local.
    """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_download_dir():
    """
    Obtiene el directorio de descargas del sistema o cae atrás al Escritorio.
    Devuelve None si no encuentra ninguno válido.
    """
    download_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
    if not os.path.exists(download_dir):
        download_dir = os.path.join(os.path.expanduser('~'), 'Desktop')
        if not os.path.exists(download_dir):
            return None
    return download_dir
