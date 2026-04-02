import os
import sys

def resource_path(relative_path):
    """
    Enables finding attached files in both local development and compiled environments.
    """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_download_dir():
    """
    Gets the system's download directory or falls back to the Desktop.
    Returns None if no valid directory is found.
    """
    download_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
    if not os.path.exists(download_dir):
        download_dir = os.path.join(os.path.expanduser('~'), 'Desktop')
        if not os.path.exists(download_dir):
            return None
    return download_dir
