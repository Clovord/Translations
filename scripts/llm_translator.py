#!/usr/bin/env python3
"""
Automatic translator for Clovord translation files.

Supports local Ollama (development) and Google Translate via deep-translator (CI).
Syncs en_US changes to target locale files: add, update, and remove keys.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple

import requests

PLACEHOLDER_RE = re.compile(r"\{[^}]+\}")

LANG_CODE_TO_NAME = {
    "de_DE": "German",
    "nl_NL": "Dutch",
    "fr_FR": "French",
    "es_ES": "Spanish",
    "it_IT": "Italian",
    "pt_BR": "Portuguese",
    "ja_JP": "Japanese",
}

LANG_CODE_TO_ISO = {
    "de_DE": "de",
    "nl_NL": "nl",
    "fr_FR": "fr",
    "es_ES": "es",
    "it_IT": "it",
    "pt_BR": "pt",
    "ja_JP": "ja",
}


def lang_name(lang_code: str) -> str:
    return LANG_CODE_TO_NAME.get(lang_code, lang_code)


def protect_placeholders(text: str) -> Tuple[str, Dict[str, str]]:
    placeholders: Dict[str, str] = {}
    protected = text
    counter = 0

    for match in PLACEHOLDER_RE.finditer(text):
        placeholder = match.group(0)
        placeholder_key = f"__PLACEHOLDER_{counter}__"
        placeholders[placeholder_key] = placeholder
        protected = protected.replace(placeholder, placeholder_key, 1)
        counter += 1

    return protected, placeholders


def restore_placeholders(text: str, placeholders: Dict[str, str]) -> str:
    result = text
    for placeholder_key, placeholder_value in placeholders.items():
        result = result.replace(placeholder_key, placeholder_value)
    return result


class TranslatorBackend(Protocol):
    def batch_translate(self, texts: Dict[str, str], target_language: str) -> Dict[str, str]:
        ...


class OllamaTranslator:
    """Translates text using local Ollama LLM."""

    def __init__(self, model: str = "neural-chat", ollama_url: str = "http://localhost:11434"):
        self.model = model
        self.ollama_url = ollama_url.rstrip("/")
        self.timeout = 60

    def check_connection(self) -> bool:
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception as exc:
            print(f"⚠️  Ollama not responding: {exc}")
            return False

    def get_available_models(self) -> List[str]:
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if response.status_code == 200:
                models_data = response.json()
                return [model["name"].split(":")[0] for model in models_data.get("models", [])]
        except Exception:
            pass
        return []

    def translate(self, text: str, target_language: str, source_language: str = "English") -> str:
        if not text or not text.strip():
            return text

        placeholder_text, placeholders = protect_placeholders(text)

        prompt = f"""Translate the following {source_language} text to {target_language}.
Keep the output concise and natural. Do not add any explanation or notes.
Preserve any placeholder markers like __PLACEHOLDER_X__ exactly as they are.

{source_language} text: {placeholder_text}

{target_language} translation:"""

        try:
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.3,
                },
                timeout=self.timeout,
            )

            if response.status_code == 200:
                result = response.json().get("response", "").strip()
                return restore_placeholders(result, placeholders)

            print(f"❌ Ollama error: {response.status_code}")
            return ""
        except requests.Timeout:
            print(f"⏱️  Translation timeout for: {text[:50]}...")
            return ""
        except Exception as exc:
            print(f"❌ Translation error: {exc}")
            return ""

    def batch_translate(self, texts: Dict[str, str], target_language: str) -> Dict[str, str]:
        results: Dict[str, str] = {}
        total = len(texts)

        print(f"🔄 Translating {total} strings to {lang_name(target_language)} via Ollama...")

        for idx, (key, text) in enumerate(texts.items(), 1):
            translated = self.translate(text, lang_name(target_language))
            results[key] = translated if translated else text

            if idx % 10 == 0:
                print(f"   [{idx}/{total}] translated...")

        print("✅ Translation complete!")
        return results


class GoogleTranslatorBackend:
    """Translates text using deep-translator (works in CI without local services)."""

    def __init__(self, batch_size: int = 40, batch_delay: float = 0.25):
        self.batch_size = batch_size
        self.batch_delay = batch_delay

    def batch_translate(self, texts: Dict[str, str], target_language: str) -> Dict[str, str]:
        from deep_translator import GoogleTranslator

        iso_code = LANG_CODE_TO_ISO.get(target_language)
        if not iso_code:
            raise ValueError(f"Unsupported target language for Google Translate: {target_language}")

        translator = GoogleTranslator(source="en", target=iso_code)
        results: Dict[str, str] = {}
        items = list(texts.items())
        total = len(items)

        print(f"🔄 Translating {total} strings to {lang_name(target_language)} via Google Translate...")

        for batch_start in range(0, total, self.batch_size):
            batch = items[batch_start : batch_start + self.batch_size]
            protected_values: List[str] = []
            placeholder_maps: List[Dict[str, str]] = []

            for _, text in batch:
                protected, placeholders = protect_placeholders(text)
                protected_values.append(protected)
                placeholder_maps.append(placeholders)

            try:
                translated_values = translator.translate_batch(protected_values)
            except Exception as exc:
                print(f"⚠️  Batch translation failed, falling back to single requests: {exc}")
                translated_values = []
                for protected in protected_values:
                    try:
                        translated_values.append(translator.translate(protected))
                    except Exception as single_exc:
                        print(f"❌ Single translation failed: {single_exc}")
                        translated_values.append("")

            for (key, original_text), translated, placeholders in zip(
                batch, translated_values, placeholder_maps
            ):
                if translated:
                    results[key] = restore_placeholders(translated, placeholders)
                else:
                    results[key] = original_text

            done = min(batch_start + self.batch_size, total)
            print(f"   [{done}/{total}] translated...")
            if done < total:
                time.sleep(self.batch_delay)

        print("✅ Translation complete!")
        return results


def create_translator(backend: str = "auto", model: str = "neural-chat", ollama_url: str = "http://localhost:11434"):
    backend = (backend or "auto").lower()

    if backend == "google":
        print("🌐 Using Google Translate backend")
        return GoogleTranslatorBackend()

    if backend == "ollama":
        translator = OllamaTranslator(model=model, ollama_url=ollama_url)
        print("🔍 Checking Ollama connection...")
        if not translator.check_connection():
            print("❌ Cannot connect to Ollama. Make sure it's running at", translator.ollama_url)
            print("   Try: ollama serve")
            return None

        available_models = translator.get_available_models()
        print(f"✅ Ollama connected. Available models: {', '.join(available_models) or 'none'}")

        if model not in available_models:
            print(f"⚠️  Model '{model}' not available. Trying to pull it...")
            os.system(f"ollama pull {model}")

        return translator

    # auto: prefer Ollama locally, fall back to Google Translate for CI
    ollama = OllamaTranslator(model=model, ollama_url=ollama_url)
    if ollama.check_connection():
        print("✅ Ollama available, using local LLM backend")
        return ollama

    print("ℹ️  Ollama unavailable, falling back to Google Translate")
    return GoogleTranslatorBackend()


class TranslationSyncer:
    """Manages translation file synchronization."""

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = base_path or Path(__file__).parent.parent
        self.categories = ["WebApp", "API", "DesktopApp", "DownloadPage", "MobileApp"]

    def get_category_path(self, category: str) -> Path:
        return self.base_path / category

    def list_target_languages(self, category: str, explicit_languages: Optional[List[str]] = None) -> List[str]:
        if explicit_languages:
            return explicit_languages

        category_path = self.get_category_path(category)
        if not category_path.exists():
            return ["de_DE", "nl_NL"]

        languages = sorted(
            path.stem
            for path in category_path.glob("*.json")
            if path.stem != "en_US"
        )
        return languages or ["de_DE", "nl_NL"]

    def load_json_file(self, category: str, language: str) -> Dict[str, str]:
        file_path = self.get_category_path(category) / f"{language}.json"
        if file_path.exists():
            with open(file_path, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        return {}

    def save_json_file(self, category: str, language: str, data: Dict[str, str]) -> bool:
        file_path = self.get_category_path(category) / f"{language}.json"
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=4, sort_keys=True)
            return True
        except Exception as exc:
            print(f"❌ Error saving {file_path}: {exc}")
            return False

    def get_keys_to_translate(
        self,
        category: str,
        target_language: str,
        old_en_us: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        en_us = self.load_json_file(category, "en_US")
        target = self.load_json_file(category, target_language)

        keys_to_translate: Dict[str, str] = {}
        for key, value in en_us.items():
            if not isinstance(value, str):
                continue

            if key not in target or not target.get(key):
                keys_to_translate[key] = value
            elif old_en_us is not None and old_en_us.get(key) != value:
                keys_to_translate[key] = value

        return keys_to_translate

    def remove_orphan_keys(self, category: str, target_language: str) -> Tuple[Dict[str, str], int]:
        en_us = self.load_json_file(category, "en_US")
        target = self.load_json_file(category, target_language)
        en_us_keys = set(en_us.keys())
        orphans = [key for key in target if key not in en_us_keys]

        for key in orphans:
            del target[key]

        return target, len(orphans)

    def sync_translations_for_category(
        self,
        category: str,
        translator: TranslatorBackend,
        languages: Optional[List[str]] = None,
        old_en_us: Optional[Dict[str, str]] = None,
    ) -> bool:
        languages = self.list_target_languages(category, languages)

        print(f"\n{'=' * 60}")
        print(f"📁 Syncing category: {category}")
        print(f"{'=' * 60}")

        category_path = self.get_category_path(category)
        if not category_path.exists():
            print(f"⚠️  Category not found: {category}")
            return False

        en_us = self.load_json_file(category, "en_US")
        if not en_us:
            print(f"⚠️  No English translations found for {category}")
            return False

        success = True

        for target_lang in languages:
            print(f"\n🌐 Processing {target_lang}...")

            current, removed_count = self.remove_orphan_keys(category, target_lang)
            if removed_count:
                print(f"   🗑️  Removed {removed_count} orphan keys")

            keys_to_translate = self.get_keys_to_translate(category, target_lang, old_en_us)

            if not keys_to_translate and removed_count == 0:
                print("   ✓ Locale already in sync")
                continue

            if keys_to_translate:
                print(f"   Found {len(keys_to_translate)} keys to translate")
                translated = translator.batch_translate(keys_to_translate, target_lang)
                current.update(translated)
            else:
                print("   ✓ No keys need translation")

            if self.save_json_file(category, target_lang, current):
                print(f"   ✅ Saved {target_lang}")
            else:
                success = False

        return success


def load_old_en_us_from_git(category: str, before_sha: str) -> Optional[Dict[str, str]]:
    if not before_sha or before_sha.startswith("000000"):
        return None

    import subprocess

    try:
        content = subprocess.check_output(
            ["git", "show", f"{before_sha}:{category}/en_US.json"],
            text=True,
        )
        data = json.loads(content)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Automatic translator for Clovord")
    parser.add_argument("--backend", default=os.getenv("TRANSLATION_BACKEND", "auto"), help="auto, ollama, or google")
    parser.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "neural-chat"), help="Ollama model to use")
    parser.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", "http://localhost:11434"), help="Ollama server URL")
    parser.add_argument("--category", action="append", default=[], help="Specific category to translate")
    parser.add_argument("--language", action="append", default=[], help="Target language codes (e.g., de_DE, nl_NL)")
    parser.add_argument("--before-sha", default=os.getenv("BEFORE_SHA", ""), help="Previous commit SHA for change detection")
    parser.add_argument("--base-path", type=Path, help="Base path to translations folder")

    args = parser.parse_args()

    translator = create_translator(backend=args.backend, model=args.model, ollama_url=args.ollama_url)
    if translator is None:
        return 1

    syncer = TranslationSyncer(base_path=args.base_path)
    languages = args.language or None
    categories = args.category or syncer.categories

    all_success = True
    for category in categories:
        old_en_us = load_old_en_us_from_git(category, args.before_sha)
        if not syncer.sync_translations_for_category(
            category,
            translator,
            languages=languages,
            old_en_us=old_en_us,
        ):
            all_success = False

    print(f"\n{'=' * 60}")
    if all_success:
        print("✅ All translations synced successfully!")
        return 0

    print("❌ Some translations failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
