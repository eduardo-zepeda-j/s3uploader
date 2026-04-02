import PyInstaller.__main__
import customtkinter
import os
import sys

def build():
    # 1. Base command structure
    args = [
        'main.py',
        '--name=s3Uploader',
        '--onefile',
        '--windowed', # Hide console
        '--noconfirm', # Overwrite building directories
    ]

    # 2. Bundle CustomTkinter Assets dynamically
    ctk_path = os.path.dirname(customtkinter.__file__)
    # Pyinstaller separator is ':' on mac/linux and ';' on windows. 
    # os.pathsep handles this automatically!
    args.append(f'--add-data={ctk_path}{os.pathsep}customtkinter')

    # 3. Bundle our local resources
    args.append(f'--add-data=locales{os.pathsep}locales')
    args.append(f'--add-data=s3icono.png{os.pathsep}.')

    # 4. Mandatory hook for TkinterDnD2 binaries cross-platform
    args.append('--collect-all=tkinterdnd2')

    # 5. Icon handling
    # Windows prefers .ico, macOS prefers .icns, PNG is acceptable but might not render native OS borders.
    args.append('--icon=s3icono.png')

    print("Executing PyInstaller with args:", args)
    PyInstaller.__main__.run(args)

if __name__ == "__main__":
    build()
