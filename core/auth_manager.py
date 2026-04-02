import os
import json
import keyring
from datetime import datetime, timedelta

class AuthManager:
    def __init__(self):
        self.config_path = os.path.join(os.path.expanduser("~"), ".s3_commander_config.json")
        self.ak_memory = ""
        self.sk_memory = ""
        self.rg_memory = ""

    def load_session(self):
        """Intenta recuperar sesión válida en memoria cache de Keyring y config."""
        if not os.path.exists(self.config_path):
            return None
        try:
            with open(self.config_path, "r") as f:
                c = json.load(f)
            last_date_str = c.get("last_login_date")
            saved_ak = c.get("saved_ak")
            rg = c.get("rg", "us-east-1")
            if last_date_str and saved_ak:
                last_date = datetime.fromisoformat(last_date_str)
                # Verifica los 90 días de validez
                if datetime.now() - last_date < timedelta(days=90):
                    sk = keyring.get_password("s3_uploader", saved_ak)
                    if sk:
                        self.ak_memory = saved_ak
                        self.sk_memory = sk
                        self.rg_memory = rg
                        return (saved_ak, sk, rg)
        except Exception:
            pass
        return None

    def save_session(self, ak, sk, rg):
        """Almacena la sesión permanentemente renovando los 90 días."""
        try:
            keyring.set_password("s3_uploader", ak, sk)
        except Exception:
            pass
        
        c = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    c = json.load(f)
            except: pass
        
        c["saved_ak"] = ak
        c["rg"] = rg
        c["last_login_date"] = datetime.now().isoformat()
        
        with open(self.config_path, "w") as f:
            json.dump(c, f)
            
        self.ak_memory = ak
        self.sk_memory = sk
        self.rg_memory = rg
        return True

    def clear_session(self):
        """Borra la memoria de forma segura destruyendo Keyring y JSON."""
        if self.ak_memory:
            try:
                keyring.delete_password("s3_uploader", self.ak_memory)
            except Exception: pass
            
        self.ak_memory = ""
        self.sk_memory = ""
        self.rg_memory = ""
        
        c = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    c = json.load(f)
            except: pass
            
        c["saved_ak"] = ""
        c["last_login_date"] = ""
        
        with open(self.config_path, "w") as f:
            json.dump(c, f)
