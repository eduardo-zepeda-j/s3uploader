import os
import xml.etree.ElementTree as ET
from utils.helpers import resource_path

class Translator:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Translator, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, lang="es"):
        if getattr(self, '_initialized', False):
            self.set_language(lang)
            return
            
        self.strings = {}
        self.current_lang = None
        self.set_language(lang)
        self._initialized = True

    def set_language(self, lang):
        if self.current_lang == lang and self.strings:
            return
        self.load_language(lang)

    def load_language(self, lang):
        self.current_lang = lang
        self.strings.clear()
        
        # Load the selected language
        file_path = resource_path(os.path.join("locales", f"{lang}.xml"))
        
        # Fallback to English if translation is missing
        if not os.path.exists(file_path) and lang != "en":
            file_path = resource_path(os.path.join("locales", "en.xml"))
            
        if os.path.exists(file_path):
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()
                for child in root:
                    if child.tag == 'string':
                        name = child.get('name')
                        text = child.text
                        if name and text is not None:
                            # Replace escaped newlines
                            text = text.replace('\\n', '\n')
                            self.strings[name] = text
            except Exception as e:
                print(f"Error loading {file_path}: {e}")

    def t(self, key, default=None):
        return self.strings.get(key, default if default else f"[{key}]")

_translator = None

def init_i18n(lang="es"):
    global _translator
    if not _translator:
        _translator = Translator(lang)
    else:
        _translator.set_language(lang)

def t(key, default=None):
    if not _translator:
        init_i18n()
    return _translator.t(key, default)

def get_lang():
    if not _translator:
        init_i18n()
    return _translator.current_lang
