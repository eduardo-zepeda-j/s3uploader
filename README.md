<div align="center">
  <img src="s3icono.png" alt="S3 Uploader Logo" width="150"/>
  <h1>AWS S3 Uploader ✨</h1>
  <p><em>Un explorador de archivos visual, rápido y moderno para Amazon S3</em></p>
  
  [![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
  [![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-blueviolet.svg)](https://github.com/TomSchimansky/CustomTkinter)
  [![Boto3](https://img.shields.io/badge/AWS-Boto3-orange.svg)](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)
  [![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Mac%20%7C%20Linux-lightgray.svg)]()
</div>

<hr/>

## 📖 Contenido

1. [Acerca del Proyecto](#-acerca-del-proyecto)
2. [Características Principales](#-características-principales)
3. [Estructura del Proyecto](#-estructura-del-proyecto)
4. [Instalación y Configuración](#-instalación-y-configuración)
5. [Uso y Flujo de Trabajo](#-uso-y-flujo-de-trabajo)
6. [Seguridad y Gestión de Sesiones](#-seguridad-y-gestión-de-sesiones)
7. [Tecnologías Utilizadas](#-tecnologías-utilizadas)

---

## 🚀 Acerca del Proyecto

**AWS S3 Uploader** es una aplicación de escritorio multiplataforma diseñada para facilitar la interacción con buckets de Amazon S3, eliminando la necesidad de interactuar constantemente con la consola web de AWS. Con un diseño sumamente cuidado y adaptativo (soporte para Modo Claro y Modo Oscuro), esta aplicación permite a los usuarios **cargar, descargar, mover, renombrar y eliminar** archivos y carpetas locales directa y visualmente en la nube.

---

## ✨ Características Principales

* **🖥️ Interfaz Moderna e Intuitiva:** Interfaz adaptable construida sobre `CustomTkinter` con modos Claro/Oscuro y un diseño tipo explorador clásico con rutas de tipo "migajas de pan" (_breadcrumbs_).
* **🔒 Seguridad Sólida de Credenciales:** En lugar de exponer credenciales, las vincula dinámicamente y las cifra a nivel de sistema usando `keyring`, manteniendo activas las sesiones por 90 días. Se puede iniciar sesión vinculando un archivo `.csv` original generado por AWS.
* **🚚 Operaciones Bulk (Masivas):** Soporte total para mover o descargar decenas o cientos de archivos al mismo tiempo hacia una nueva ubicación. 
* **📂 Soporte Drag & Drop:** Arrastra archivos y carpetas directamente desde tu ordenador hacia la aplicación para que comience la subida a S3 de manera automática.
* **📈 Hilos y Concurrencia:** La interfaz principal no se congela ante operaciones pesadas (descargas y subidas enormes). Emplea callbacks paralelos para reflejar el estado actual utilizando barras de progreso de alta precisión.
* **🛡️ Borrado Seguro:** Operaciones destructivas como la eliminación definitiva requieren aprobación doble y exigen un código PIN de seguridad configurable por el usuario.
* **⚙️ Clases de Almacenamiento Dinámicas:** Asigna si deseas guardar archivos como `STANDARD`, `GLACIER_IR`, `DEEP_ARCHIVE` u `ONEZONE_IA` desde un ligero selector en la barra de herramientas.

---

## 📂 Estructura del Proyecto

El código está organizado siguiendo un principio de Modularidad y separación de responsabilidades:

```text
AWS-S3-UPLOADER/
│   main.py               # Punto de entrada principal
│   requirements.txt      # Dependencias del proyecto
│   s3icono.png           # Icono de la aplicación
│
├── core/                 # Lógica de Backend
│   ├── auth_manager.py   # Controlador de inicio de sesión y Keyring
│   └── s3_manager.py     # SDK nativo de Boto3 para operaciones de S3
│
├── ui/                   # Lógica e interfaces Frontend
│   ├── explorer_window.py# Interfaz principal (Dashboard)
│   ├── login_window.py   # Ventana de Autenticación
│   └── move_modal.py     # Funcionalidad y vista para mover/trasladar S3 elements
│
└── utils/                # Utilidades Generales
    └── helpers.py        # Funciones transversales (ej. obtener carpeta descargas)
```

---

## 💻 Instalación y Configuración

### Prerrequisitos
Asegúrate de contar con **Python 3.12** o superior instalado en tu máquina.

1. Clona este repositorio:
```bash
git clone https://github.com/tu-usuario/aws-s3-uploader.git
cd aws-s3-uploader
```

2. Crea tu entorno virtual (Recomendado):
```bash
python3 -m venv venv
# Activar en Windows:
venv\Scripts\activate
# Activar en Mac/Linux:
source venv/bin/activate
```

3. Instala las dependencias:
```bash
pip install -r requirements.txt
```

---

## 🕹️ Uso y Flujo de Trabajo

### Iniciar la aplicación
Simplemente ejecuta el script principal:
```bash
python3 main.py
```

### Funciones Claves 

1. **Gestión de Archivos / Interacción Directa:** 
   * Podrás ver un panel lateral con tus buckets a la izquierda. 
   * La vista principal renderizará íconos únicos por tipo de archivo (`.jpg`, `.mp4`, `.pdf`, y docenas más), extraídos en $O(1)$ permitiendo agilizar enormemente operaciones estresantes.
2. **Generación de Enlaces Temporales:**
   * Al hacer clic en el ícono de candado/link (`🔗`) junto a los archivos en la vista de lista, se generará una URL firmada y se copiará instantáneamente a tu portapapeles.
3. **Módulo de Mover (Move Modal):**
   * Selecciona recursos masivos, da click en "Mover Slc." y se activará un módulo que permite navegar virtualmente todos los destinos posibles sin necesidad de actualizar la ventana principal, permitiéndote cambiar objetos de un bucket a otro o de carpeta a carpeta dinámicamente.

---

## 🔐 Seguridad y Gestión de Sesiones

Al iniciar por primera vez, el sistema pedirá un archivo de acceso `.csv` generado por IAM en AWS. 
La aplicación:
* Excluye del Git elementos de PyInstaller o archivos de compilación temporal (`.gitignore` rigurosamente configurado).
* Guarda tu `access_key` en memoria temporal y confía tu `secret_key` al sistema de seguridad Keychain Nativo de tu ordenador (Keychain Access en Mac, Credential Manager en Windows). Todo a través del módulo `core.auth_manager.py`.

> [!WARNING]
> Recuerda nunca comprometer el archivo local `config.json` que la aplicación puede crear por si misma. Sirve para recordar la última ruta accedida y tu clave de seguridad anti-eliminaciones.

---

## 🛠️ Tecnologías Utilizadas

* **[CustomTkinter](https://github.com/TomSchimansky/CustomTkinter):** Framework de interfaz gráfica de usuario.
* **[Boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html):** AWS SDK oficial para Python.
* **[TkinterDnD2](https://pypi.org/project/tkinterdnd2/):** Librería que habilita interacciones de Drag & Drop (arrastrar y soltar) sin perder la portabilidad a las dependencias clásicas.
* **[Keyring](https://pypi.org/project/keyring/):** Framework seguro encriptado del sistema.

---
<div align="center">
Desarrollado con ❤️ por <b>Eduardo Zepeda</b>.
</div>
