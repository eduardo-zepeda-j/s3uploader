import customtkinter as ctk
from core.auth_manager import AuthManager
from ui.explorer_window import S3UniversalApp

def main():
    ctk.set_appearance_mode("dark")
    app = S3UniversalApp()
    app.mainloop()

if __name__ == "__main__":
    main()
