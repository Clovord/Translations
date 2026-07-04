#!/usr/bin/env python3
"""
Webhook handler for automatic LLM translation on en_US changes.
This gets triggered by the sync-translations workflow.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
import urllib.request
import urllib.error


def get_changed_files(before_sha: str, head_sha: str) -> List[str]:
    """Get list of changed translation files"""
    try:
        if before_sha.startswith("000000"):
            # New repo or first commit
            cmd = ["git", "ls-tree", "-r", "--name-only", head_sha]
        else:
            cmd = ["git", "diff", "--name-only", f"{before_sha}..{head_sha}"]
        
        result = subprocess.check_output(cmd, text=True).strip()
        return [f for f in result.splitlines() if f.strip()]
    except Exception as e:
        print(f"Error getting changed files: {e}")
        return []


def extract_changed_categories(changed_files: List[str]) -> Dict[str, List[str]]:
    """
    Extract which categories have changed
    
    Returns:
        Dict mapping category -> list of language files changed
        e.g., {"WebApp": ["en_US.json"], "API": ["en_US.json"]}
    """
    categories = {}
    
    for file_path in changed_files:
        parts = file_path.split("/")
        if len(parts) >= 2 and parts[1].endswith(".json"):
            category = parts[0]
            language_file = parts[1]
            
            if category not in categories:
                categories[category] = []
            categories[category].append(language_file)
    
    return categories


def should_trigger_translation(changed_categories: Dict[str, List[str]]) -> bool:
    """Check if en_US files were changed (should trigger translation)"""
    for category, files in changed_categories.items():
        if "en_US.json" in files:
            return True
    return False


def get_categories_to_translate(changed_categories: Dict[str, List[str]]) -> List[str]:
    """Get list of categories that have en_US changes"""
    categories = []
    for category, files in changed_categories.items():
        if "en_US.json" in files:
            categories.append(category)
    return categories


def run_translation(categories: List[str], target_languages: List[str] = None) -> bool:
    """
    Run the LLM translator for specified categories
    
    Args:
        categories: List of categories to translate (e.g., ["WebApp", "API"])
        target_languages: List of target language codes (default: ["de_DE", "nl_NL"])
    
    Returns:
        True if successful
    """
    if target_languages is None:
        target_languages = ["de_DE", "nl_NL"]
    
    script_path = Path(__file__).parent / "llm_translator.py"
    
    if not script_path.exists():
        print(f"❌ Translation script not found: {script_path}")
        return False
    
    print(f"\n🚀 Triggering LLM translations...")
    print(f"   Categories: {', '.join(categories)}")
    print(f"   Languages: {', '.join(target_languages)}")
    
    try:
        # Build command
        cmd = ["python", str(script_path)]
        
        for category in categories:
            cmd.extend(["--category", category])
        
        for lang in target_languages:
            cmd.extend(["--language", lang])
        
        # Run translation
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"\n✅ Translation successful!")
            if result.stdout:
                print(result.stdout)
            return True
        else:
            print(f"\n❌ Translation failed!")
            if result.stdout:
                print("STDOUT:", result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            return False
    
    except Exception as e:
        print(f"❌ Error running translation: {e}")
        return False


def commit_changes(categories: List[str]) -> bool:
    """
    Commit translated changes back to git
    
    Args:
        categories: List of categories that were translated
    
    Returns:
        True if successful
    """
    try:
        # Check if there are changes
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            text=True
        ).strip()
        
        if not status:
            print("✓ No translation changes to commit")
            return True
        
        print("\n📝 Committing translation changes...")
        
        # Add all JSON files
        for category in categories:
            subprocess.run([
                "git", "add",
                f"{category}/de_DE.json",
                f"{category}/nl_NL.json"
            ])
        
        # Commit
        commit_msg = f"chore: auto-translate {', '.join(categories)}"
        subprocess.run([
            "git", "commit",
            "-m", commit_msg,
            "--author=Clovord Bot <bot@clovord.com>"
        ])
        
        # Push
        subprocess.run(["git", "push"])
        
        print("✅ Changes committed and pushed!")
        return True
    
    except Exception as e:
        print(f"❌ Error committing changes: {e}")
        return False


def send_webhook_notification(message: str, status: str = "success") -> bool:
    """
    Send webhook notification to central webhook server
    
    Args:
        message: Notification message
        status: Status (success, error, warning)
    
    Returns:
        True if successful
    """
    webhook_url = os.getenv("TRANSLATION_WEBHOOK_URL")
    webhook_token = os.getenv("TRANSLATION_WEBHOOK_TOKEN")
    
    if not webhook_url:
        print("ℹ️  No webhook URL configured, skipping notification")
        return True
    
    try:
        payload = {
            "status": status,
            "message": message,
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {webhook_token}" if webhook_token else None,
        }
        
        # Remove None headers
        headers = {k: v for k, v in headers.items() if v is not None}
        
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers=headers,
            method="POST"
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            print(f"📨 Webhook notification sent: {response.status}")
            return response.status == 200
    
    except Exception as e:
        print(f"⚠️  Error sending webhook: {e}")
        return False


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Webhook handler for auto-translation on en_US changes"
    )
    parser.add_argument("--before-sha", help="Before commit SHA")
    parser.add_argument("--head-sha", help="Head commit SHA")
    parser.add_argument("--target-languages", nargs="+", default=["de_DE", "nl_NL"])
    parser.add_argument("--auto-commit", action="store_true", help="Auto-commit and push changes")
    
    args = parser.parse_args()
    
    # Get environment variables as fallback
    before_sha = args.before_sha or os.getenv("BEFORE_SHA", "")
    head_sha = args.head_sha or os.getenv("HEAD_SHA", "")
    
    print("="*60)
    print("🔄 Translation Webhook Handler")
    print("="*60)
    
    if not head_sha:
        print("❌ HEAD_SHA not provided")
        return 1
    
    # Get changed files
    changed_files = get_changed_files(before_sha, head_sha)
    print(f"\n📋 Changed files: {len(changed_files)}")
    
    if not changed_files:
        print("ℹ️  No files changed")
        return 0
    
    # Extract changed categories
    changed_categories = extract_changed_categories(changed_files)
    print(f"📂 Changed categories: {list(changed_categories.keys())}")
    
    # Check if en_US changed
    if not should_trigger_translation(changed_categories):
        print("ℹ️  No en_US changes detected, skipping translation")
        return 0
    
    # Get categories to translate
    categories_to_translate = get_categories_to_translate(changed_categories)
    print(f"\n🎯 Categories to translate: {categories_to_translate}")
    
    # Run translation
    if not run_translation(categories_to_translate, args.target_languages):
        send_webhook_notification(
            f"Translation failed for: {', '.join(categories_to_translate)}",
            status="error"
        )
        return 1
    
    # Optional: Auto-commit
    if args.auto_commit:
        if not commit_changes(categories_to_translate):
            print("⚠️  Failed to commit changes")
            return 1
    
    # Send success notification
    send_webhook_notification(
        f"Successfully auto-translated {', '.join(categories_to_translate)} to {', '.join(args.target_languages)}",
        status="success"
    )
    
    print("\n✅ Webhook handler complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
