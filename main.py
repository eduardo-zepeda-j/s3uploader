import os
import json
import customtkinter as ctk
from core.auth_manager import AuthManager
from ui.explorer_window import S3UniversalApp
from core.i18n import init_i18n

def main():
    # Detect language from config
    config_path = os.path.join(os.path.expanduser("~"), ".s3_commander_config.json")
    lang = "es"
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                c = json.load(f)
                lang = c.get("language", "es")
        except: pass
        
    init_i18n(lang)
    
    ctk.set_appearance_mode("dark")
    app = S3UniversalApp()
    app.mainloop()

if __name__ == "__main__":
    main()
