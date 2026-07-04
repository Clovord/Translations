#!/usr/bin/env python3
"""
Setup script for LLM-based automatic translation system.
Checks Ollama installation and configures the translation environment.
"""

import subprocess
import sys
import os
from pathlib import Path


def check_ollama_installed() -> bool:
    """Check if Ollama is installed"""
    try:
        result = subprocess.run(["ollama", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Ollama installed: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    print("❌ Ollama not found")
    return False


def check_ollama_running() -> bool:
    """Check if Ollama server is running"""
    try:
        import requests
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        print(f"✅ Ollama server running")
        return response.status_code == 200
    except:
        print("❌ Ollama server not running")
        print("   Start it with: ollama serve")
        return False


def install_ollama() -> bool:
    """Guide user to install Ollama"""
    print("\n📦 Installing Ollama...")
    print("\nVisit: https://ollama.ai")
    print("\nOr use your package manager:")
    
    if sys.platform == "darwin":
        print("  brew install ollama")
    elif sys.platform == "linux":
        print("  curl https://ollama.ai/install.sh | sh")
    elif sys.platform == "win32":
        print("  Download from: https://ollama.ai/download")
    
    return False


def pull_model(model_name: str = "neural-chat") -> bool:
    """Pull a model from Ollama registry"""
    try:
        print(f"\n🚀 Pulling model: {model_name}")
        print("   This may take a few minutes...")
        
        result = subprocess.run(
            ["ollama", "pull", model_name],
            capture_output=False,
            text=True
        )
        
        if result.returncode == 0:
            print(f"✅ Model {model_name} installed successfully")
            return True
        else:
            print(f"❌ Failed to pull model {model_name}")
            return False
    except Exception as e:
        print(f"❌ Error pulling model: {e}")
        return False


def list_available_models() -> list:
    """List available models in Ollama"""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")[1:]  # Skip header
            models = []
            for line in lines:
                parts = line.split()
                if parts:
                    models.append(parts[0])
            return models
    except:
        pass
    
    return []


def setup_environment():
    """Setup environment variables"""
    print("\n🔧 Setting up environment...")
    
    # Create .env file template if it doesn't exist
    env_file = Path(".env")
    if not env_file.exists():
        env_content = """# Ollama Configuration
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=neural-chat

# Auto-translation settings
AUTO_TRANSLATE_ENABLED=true
TARGET_LANGUAGES=de_DE,nl_NL

# GitHub settings (optional)
GITHUB_TOKEN=
"""
        env_file.write_text(env_content)
        print(f"✅ Created .env file template")
    else:
        print(f"ℹ️  .env file already exists")


def main():
    print("=" * 60)
    print("🌍 LLM Translation System Setup")
    print("=" * 60)
    
    # Check Ollama installation
    if not check_ollama_installed():
        print("\n📥 Ollama not installed. Installing...")
        if install_ollama():
            print("✅ Please restart the installation after installing Ollama")
            return 1
        else:
            return 1
    
    # Start Ollama if not running
    if not check_ollama_running():
        print("\n🚀 Starting Ollama server...")
        try:
            # Try to start Ollama in the background
            if sys.platform == "win32":
                subprocess.Popen(["ollama", "serve"], creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen(["ollama", "serve"])
            
            import time
            time.sleep(3)
            
            if not check_ollama_running():
                print("❌ Could not start Ollama")
                return 1
        except Exception as e:
            print(f"❌ Error starting Ollama: {e}")
            return 1
    
    # Check/install models
    print("\n📚 Checking translation models...")
    models = list_available_models()
    
    if models:
        print(f"   Available models: {', '.join(models)}")
    
    if "neural-chat" not in models:
        print("\n   Recommended model not found: neural-chat")
        if input("   Download it now? (y/n): ").lower() == 'y':
            pull_model("neural-chat")
    
    if "mistral" not in models:
        print("\n   Alternative model available: mistral (smaller, faster)")
        if input("   Download it? (y/n): ").lower() == 'y':
            pull_model("mistral")
    
    # Setup environment
    setup_environment()
    
    # Test the translator
    print("\n🧪 Testing translator...")
    try:
        from llm_translator import OllamaTranslator
        
        translator = OllamaTranslator()
        
        if translator.check_connection():
            test_text = "Hello, how are you today?"
            result = translator.translate(test_text, "German")
            
            if result:
                print(f"✅ Translation test successful!")
                print(f"   English: {test_text}")
                print(f"   German:  {result}")
            else:
                print("⚠️  Translation returned empty result")
        else:
            print("❌ Cannot connect to Ollama")
            return 1
    
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        return 1
    
    # Final status
    print("\n" + "=" * 60)
    print("✅ Setup complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Review the .env file configuration")
    print("2. Run: python llm_translator.py --help")
    print("3. Test with: python llm_translator.py --category WebApp")
    print("\nTo integrate with GitHub Actions:")
    print("  - The sync-translations-with-llm.yml workflow is ready")
    print("  - Configure it to run on your server")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
