import os
import json
import customtkinter as ctk
from core.auth_manager import AuthManager
from ui.explorer_window import S3UniversalApp
from core.i18n import init_i18n

def main():
    while True:
        # 1. Detect language gracefully before ANY Tkinter instances are bootstrapped
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
        
        # 2. Main app initialization
        app = S3UniversalApp()
        
        # 3. Blocking GUI Mainloop (the process sleeps here until window is closed)
        app.mainloop()
        
        # 4. Determine exit condition based on GUI state flags upon shutdown
        if getattr(app, "should_restart", False):
            # Inner-process GUI reboot. Proceed to next loop iteration.
            continue
        else:
            # Clean exit
            break

if __name__ == "__main__":
    main()
