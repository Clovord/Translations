#!/usr/bin/env python3
"""
LLM-based translator using local Ollama for automatic translation.
Integrates with the translation sync workflow to auto-translate en_US changes.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List
import requests
from difflib import unified_diff


class OllamaTranslator:
    """Translates text using local Ollama LLM"""
    
    def __init__(self, model: str = "neural-chat", ollama_url: str = "http://localhost:11434"):
        self.model = model
        self.ollama_url = ollama_url.rstrip("/")
        self.timeout = 60
        
    def check_connection(self) -> bool:
        """Check if Ollama is running"""
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception as e:
            print(f"⚠️  Ollama not responding: {e}")
            return False
    
    def get_available_models(self) -> List[str]:
        """Get list of available models"""
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if response.status_code == 200:
                models_data = response.json()
                return [model["name"].split(":")[0] for model in models_data.get("models", [])]
        except:
            pass
        return []
    
    def translate(self, text: str, target_language: str, source_language: str = "English") -> str:
        """
        Translate text using Ollama LLM
        
        Args:
            text: Text to translate
            target_language: Target language (e.g., "German", "Dutch")
            source_language: Source language (default: English)
        
        Returns:
            Translated text or empty string if translation failed
        """
        if not text or not text.strip():
            return text
        
        # Preserve placeholders like {date}, {id}, etc.
        placeholders = {}
        placeholder_text = text
        counter = 0
        
        import re
        for match in re.finditer(r'\{[^}]+\}', text):
            placeholder = match.group(0)
            placeholder_key = f"__PLACEHOLDER_{counter}__"
            placeholders[placeholder_key] = placeholder
            placeholder_text = placeholder_text.replace(placeholder, placeholder_key, 1)
            counter += 1
        
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
                    "temperature": 0.3,  # Lower temp for more consistent translations
                },
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json().get("response", "").strip()
                
                # Restore placeholders
                for placeholder_key, placeholder_value in placeholders.items():
                    result = result.replace(placeholder_key, placeholder_value)
                
                return result
            else:
                print(f"❌ Ollama error: {response.status_code}")
                return ""
                
        except requests.Timeout:
            print(f"⏱️  Translation timeout for: {text[:50]}...")
            return ""
        except Exception as e:
            print(f"❌ Translation error: {e}")
            return ""
    
    def batch_translate(self, texts: Dict[str, str], target_language: str) -> Dict[str, str]:
        """
        Translate multiple texts efficiently
        
        Args:
            texts: Dict of {key: text_to_translate}
            target_language: Target language
        
        Returns:
            Dict of {key: translated_text}
        """
        results = {}
        total = len(texts)
        
        print(f"🔄 Translating {total} strings to {target_language}...")
        
        for idx, (key, text) in enumerate(texts.items(), 1):
            translated = self.translate(text, target_language)
            results[key] = translated if translated else text
            
            if idx % 10 == 0:
                print(f"   [{idx}/{total}] translated...")
        
        print(f"✅ Translation complete!")
        return results


class TranslationSyncer:
    """Manages translation file synchronization"""
    
    def __init__(self, base_path: Path = None):
        self.base_path = base_path or Path(__file__).parent.parent
        self.categories = ["WebApp", "API", "DesktopApp", "DownloadPage"]
        
    def get_category_path(self, category: str) -> Path:
        """Get path to translation category"""
        return self.base_path / category
    
    def load_json_file(self, category: str, language: str) -> Dict[str, str]:
        """Load translation JSON file"""
        file_path = self.get_category_path(category) / f"{language}.json"
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def save_json_file(self, category: str, language: str, data: Dict[str, str]) -> bool:
        """Save translation JSON file"""
        file_path = self.get_category_path(category) / f"{language}.json"
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4, sort_keys=True)
            return True
        except Exception as e:
            print(f"❌ Error saving {file_path}: {e}")
            return False
    
    def get_missing_keys(self, category: str, target_language: str) -> Dict[str, str]:
        """Get keys that are in en_US but missing in target language"""
        en_us = self.load_json_file(category, "en_US")
        target = self.load_json_file(category, target_language)
        
        missing = {}
        for key, value in en_us.items():
            if key not in target or not target[key]:
                missing[key] = value
        
        return missing
    
    def get_changed_keys(self, category: str, old_en_us: Dict[str, str], new_en_us: Dict[str, str]) -> Dict[str, str]:
        """Get keys that have changed in en_US"""
        changed = {}
        for key, new_value in new_en_us.items():
            old_value = old_en_us.get(key)
            if old_value != new_value:
                changed[key] = new_value
        return changed
    
    def sync_translations_for_category(self, category: str, translator: OllamaTranslator, 
                                      languages: List[str] = None) -> bool:
        """
        Sync translations for a category to multiple target languages
        
        Args:
            category: Translation category (e.g., "WebApp")
            translator: OllamaTranslator instance
            languages: List of target languages (default: ["de_DE", "nl_NL"])
        
        Returns:
            True if successful
        """
        if languages is None:
            languages = ["de_DE", "nl_NL"]
        
        print(f"\n{'='*60}")
        print(f"📁 Syncing category: {category}")
        print(f"{'='*60}")
        
        # Check if category exists
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
            
            # Get missing and changed keys
            missing = self.get_missing_keys(category, target_lang)
            
            if not missing:
                print(f"   ✓ All strings already translated")
                continue
            
            print(f"   Found {len(missing)} keys to translate")
            
            # Translate missing keys
            translated = translator.batch_translate(missing, self._lang_name(target_lang))
            
            # Update the target language file
            current = self.load_json_file(category, target_lang)
            current.update(translated)
            
            if self.save_json_file(category, target_lang, current):
                print(f"   ✅ Saved {target_lang} with {len(translated)} translations")
            else:
                success = False
        
        return success
    
    @staticmethod
    def _lang_name(lang_code: str) -> str:
        """Convert language code to full name"""
        mapping = {
            "de_DE": "German",
            "nl_NL": "Dutch",
            "fr_FR": "French",
            "es_ES": "Spanish",
            "it_IT": "Italian",
            "pt_BR": "Portuguese",
            "ja_JP": "Japanese",
        }
        return mapping.get(lang_code, "English")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="LLM-based translator for Clovord")
    parser.add_argument("--model", default="neural-chat", help="Ollama model to use")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama server URL")
    parser.add_argument("--category", help="Specific category to translate (WebApp, API, etc.)")
    parser.add_argument("--language", action="append", default=[], help="Target language codes (e.g., de_DE, nl_NL)")
    parser.add_argument("--base-path", type=Path, help="Base path to translations folder")
    
    args = parser.parse_args()
    
    # Initialize
    translator = OllamaTranslator(model=args.model, ollama_url=args.ollama_url)
    syncer = TranslationSyncer(base_path=args.base_path)
    
    # Check Ollama connection
    print("🔍 Checking Ollama connection...")
    if not translator.check_connection():
        print("❌ Cannot connect to Ollama. Make sure it's running at", translator.ollama_url)
        print("   Try: ollama serve")
        return 1
    
    available_models = translator.get_available_models()
    print(f"✅ Ollama connected. Available models: {', '.join(available_models)}")
    
    if args.model not in available_models:
        print(f"⚠️  Model '{args.model}' not available. Trying to pull it...")
        os.system(f"ollama pull {args.model}")
    
    # Determine what to translate
    languages = args.language if args.language else ["de_DE", "nl_NL"]
    
    if args.category:
        categories = [args.category]
    else:
        categories = syncer.categories
    
    # Sync each category
    all_success = True
    for category in categories:
        if not syncer.sync_translations_for_category(category, translator, languages):
            all_success = False
    
    print(f"\n{'='*60}")
    if all_success:
        print("✅ All translations synced successfully!")
        return 0
    else:
        print("❌ Some translations failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
