import PyInstaller.__main__
import customtkinter
import os
import sys

def build():
    # 1. Base command structure
    args = [
        'main.py',
        '--name=s3Uploader',
        '--windowed', # Hide console
        '--noconfirm', # Overwrite building directories
    ]

    # For Windows and Linux, we use --onefile for simplicity.
    # For macOS, --onefile combined with Gatekeeper causes severe loading delays since it has to extract to /tmp. 
    # Without --onefile, windowed PyInstaller automatically creates a beautiful standalone `.app` bundle natively.
    if sys.platform != "darwin":
        args.append('--onefile')

    # 2. Bundle CustomTkinter Assets dynamically
    ctk_path = os.path.dirname(customtkinter.__file__)
    # Pyinstaller separator is ':' on mac/linux and ';' on windows. 
    # os.pathsep handles this automatically!
    args.append(f'--add-data={ctk_path}{os.pathsep}customtkinter')

    # 3. Bundle our local resources
    args.append(f'--add-data=locales{os.pathsep}locales')
    args.append(f'--add-data=s3icono.png{os.pathsep}.')

    # 4. Mandatory hooks
    args.append('--collect-all=tkinterdnd2')
    args.append('--collect-all=keyring') # Required for Windows Credential backends

    # 5. Icon handling
    args.append('--icon=s3icono.png')

    print("Executing PyInstaller with args:", args)
    PyInstaller.__main__.run(args)

if __name__ == "__main__":
    build()
