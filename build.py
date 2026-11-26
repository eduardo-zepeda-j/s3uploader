import PyInstaller.__main__
import customtkinter
import os
import sys
import platform
import subprocess
import shutil

def create_icns(png_path="s3icono.png", icns_path="s3icono.icns"):
    """Generates a macOS .icns file from a PNG image using native macOS tools."""
    if not os.path.exists(png_path):
        return None
    iconset_dir = "s3icono.iconset"
    os.makedirs(iconset_dir, exist_ok=True)
    try:
        sizes = [16, 32, 64, 128, 256, 512]
        for s in sizes:
            subprocess.run(['sips', '-z', str(s), str(s), png_path, '--out', f'{iconset_dir}/icon_{s}x{s}.png'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if s * 2 <= 1024:
                subprocess.run(['sips', '-z', str(s * 2), str(s * 2), png_path, '--out', f'{iconset_dir}/icon_{s}x{s}@2x.png'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['iconutil', '-c', 'icns', iconset_dir, '-o', icns_path], check=True)
        return icns_path
    except Exception as e:
        print(f"Warning: Failed to generate .icns ({e})")
        return None
    finally:
        if os.path.exists(iconset_dir):
            shutil.rmtree(iconset_dir)

def create_dmg(app_bundle_path, output_dmg_path):
    """Packages the .app bundle into a user-friendly .dmg with an Applications shortcut."""
    staging_dir = "dist/dmg_staging"
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir)
    os.makedirs(staging_dir, exist_ok=True)

    try:
        app_name = os.path.basename(app_bundle_path)
        dest_app = os.path.join(staging_dir, app_name)
        subprocess.run(['cp', '-R', app_bundle_path, dest_app], check=True)
        os.symlink('/Applications', os.path.join(staging_dir, 'Applications'))

        print(f"Creating DMG at {output_dmg_path}...")
        subprocess.run([
            'hdiutil', 'create',
            '-volname', 's3Uploader',
            '-srcfolder', staging_dir,
            '-ov',
            '-format', 'UDZO',
            output_dmg_path
        ], check=True)
        print("DMG created successfully!")
    finally:
        if os.path.exists(staging_dir):
            shutil.rmtree(staging_dir)

def build():
    # 1. Base command structure
    args = [
        'main.py',
        '--name=s3Uploader',
        '--windowed', # Hide console
        '--noconfirm', # Overwrite building directories
    ]

    is_mac = sys.platform == "darwin"

    # For Windows and Linux, we use --onefile for simplicity.
    # For macOS, without --onefile, windowed PyInstaller automatically creates a native .app bundle.
    if not is_mac:
        args.append('--onefile')

    # 2. Bundle CustomTkinter Assets dynamically
    ctk_path = os.path.dirname(customtkinter.__file__)
    args.append(f'--add-data={ctk_path}{os.pathsep}customtkinter')

    # 3. Bundle our local resources
    args.append(f'--add-data=locales{os.pathsep}locales')
    args.append(f'--add-data=s3icono.png{os.pathsep}.')

    # 4. Mandatory hooks
    args.append('--collect-all=tkinterdnd2')
    args.append('--collect-all=keyring')

    # 5. Icon handling & macOS specifics
    if is_mac:
        icns_file = "s3icono.icns"
        if not os.path.exists(icns_file) and os.path.exists("s3icono.png"):
            create_icns("s3icono.png", icns_file)
        
        if os.path.exists(icns_file):
            args.append(f'--icon={icns_file}')
        else:
            args.append('--icon=s3icono.png')

        arch = platform.machine() # arm64 on Apple Silicon
        args.append(f'--target-arch={arch}')
        args.append('--osx-bundle-identifier=com.s3uploader.app')
    else:
        args.append('--icon=s3icono.png')

    print("Executing PyInstaller with args:", args)
    PyInstaller.__main__.run(args)

    # 6. Post-build steps for macOS (Ad-hoc signing & DMG creation)
    if is_mac:
        app_path = os.path.join("dist", "s3Uploader.app")
        if os.path.exists(app_path):
            print("Re-signing macOS .app bundle ad-hoc...")
            subprocess.run(['codesign', '--force', '--deep', '--sign', '-', app_path], check=False)

            arch_name = "arm64" if platform.machine() == "arm64" else platform.machine()
            dmg_path = os.path.join("dist", f"s3Uploader-mac-{arch_name}.dmg")
            create_dmg(app_path, dmg_path)
            print(f"\nBuild complete! Output files:\n- App bundle: {app_path}\n- DMG installer: {dmg_path}")

if __name__ == "__main__":
    build()
