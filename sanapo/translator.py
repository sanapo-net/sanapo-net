# sanapo/translator.py
from __future__ import annotations
import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sanapo.logger import Logger
    from sanapo.config import Config

class Translator:
    """Static string translator with key-based lookup from JSON files."""
    def __init__(self, config: Config, logger: Logger, lang: str = "en"):
        self._logger: Logger = logger
        self._lang_dir = config.TRANSLATOR_DIR
        self._current_lang = lang or config.UI_LANGUAGE
        # Dictionary storage: { "Key text": "translated target text" }.
        self._dict: dict[str, str] = {}
        self.load_lang_json(self._current_lang)

    def load_lang_json(self, lang_code: str) -> bool:
        """Loads a translation dictionary from a JSON file (e.g., 'ru.json')."""
        file_path = os.path.join(self._lang_dir, f"{lang_code}.json")
        
        if not os.path.exists(file_path):
            self._logger.wrn("language file {path} not found", path=file_path)
            return False

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self._dict = json.load(f)
                self._current_lang = lang_code
                return True
        except (json.JSONDecodeError, IOError) as e:
            self._logger.err("failed to load {lang_code}, error: {e}", lang_code=lang_code, e=e)
            return False

    def translate(self, text: str, **kwargs) -> str:
        """
        Looks up the key in the dictionary and formats it with kwargs. 
        Example: translate("Found {n} units", n=5) -> "Найдено 5 юнитов"
        """
        # Get translation or fallback to original text.
        template = self._dict.get(text, text)
        
        if not kwargs:
            return template

        try:
            # Safely inject variables into the template.
            return template.format(**kwargs)
        except KeyError as e:
            # If a variable is missing in kwargs, return template with raw keys.
            self._logger.err("missing variable {e} for text: {text}", e=e, text=text)
            return template
        except Exception as e:
            self._logger.err("formatting error: {e}", e=e)
            return template

    @property
    def current_lang(self) -> str:
        return self._current_lang

"""
Example file ru.json:
json{
    "Unit {name} started": "Юнит {name} запущен",
    "System error: {code}": "Системная ошибка: {code}"
}
"""