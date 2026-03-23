"""
KoeGuide Prompt Builder - Builds and deploys agent prompt with scraped data.

Combines the base Mado prompt + Client Actions instructions + scraped municipality data
and deploys to Vocal Bridge via `vb prompt set`.

Usage:
    python prompt_builder.py build    # Build and show prompt (dry run)
    python prompt_builder.py deploy   # Build and deploy to Vocal Bridge
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from scraper import get_all_cached_data, load_municipalities

BASE_DIR = Path(__file__).parent
BASE_PROMPT_FILE = BASE_DIR / "prompt_base.txt"
CLIENT_ACTIONS_FILE = BASE_DIR / "prompt-addition.txt"


def format_structured_data(cached):
    """Format structured LLM-extracted data into prompt text."""
    structured = cached["structured"]
    lines = [f"### {cached['municipality']}"]
    if cached.get("municipality_en"):
        lines[0] += f" ({cached['municipality_en']})"
    lines.append(f"Source: {cached['source_url']} (scraped: {cached['scraped_at'][:10]})")
    lines.append("")

    categories = structured.get("categories", [])
    if categories:
        lines.append("**Collection Schedule:**")
        for cat in categories:
            name = cat.get("name", "")
            name_en = cat.get("name_en", "")
            schedule = cat.get("schedule", "")
            label = f"{name} ({name_en})" if name_en else name
            lines.append(f"- **{label}**: {schedule}")
            items = cat.get("items", [])
            if items:
                lines.append(f"  Items: {', '.join(items[:10])}")
            bag = cat.get("bag_type")
            if bag:
                lines.append(f"  Bag: {bag}")
            rules = cat.get("rules")
            if rules:
                lines.append(f"  Rules: {rules}")
        lines.append("")

    general = structured.get("general_rules")
    if general:
        lines.append(f"**General Rules:** {general}")
        lines.append("")

    oversized = structured.get("oversized_items")
    if oversized:
        lines.append("**Oversized Items (粗大ゴミ):**")
        if oversized.get("how_to"):
            lines.append(f"- How to: {oversized['how_to']}")
        if oversized.get("phone"):
            lines.append(f"- Phone: {oversized['phone']}")
        if oversized.get("fee"):
            lines.append(f"- Fee: {oversized['fee']}")
        lines.append("")

    contact = structured.get("contact")
    if contact:
        lines.append(f"**Contact:** {contact}")
        lines.append("")

    notes = structured.get("notes")
    if notes:
        lines.append(f"**Notes:** {notes}")
        lines.append("")

    return "\n".join(lines)


def format_raw_text(cached):
    """Format raw scraped text into prompt text (fallback when no LLM extraction)."""
    lines = [f"### {cached['municipality']}"]
    if cached.get("municipality_en"):
        lines[0] += f" ({cached['municipality_en']})"
    lines.append(f"Source: {cached['source_url']} (scraped: {cached['scraped_at'][:10]})")
    lines.append("")
    lines.append("The following is extracted text from the municipality's garbage collection page.")
    lines.append("Use this information to answer questions about garbage disposal in this area:")
    lines.append("")

    # Truncate raw text to keep prompt manageable
    raw = cached.get("raw_text", "")
    if len(raw) > 5000:
        raw = raw[:5000] + "\n\n[... additional content truncated ...]"
    lines.append(raw)
    lines.append("")

    return "\n".join(lines)


def build_garbage_section(all_cached):
    """Build the municipality-specific garbage data section."""
    if not all_cached:
        return ""

    sections = []
    sections.append("\n## Municipality-Specific Garbage Collection Data")
    sections.append("Use the following REAL data from municipal websites when answering garbage-related questions.")
    sections.append("This data was scraped from official municipal websites and should be treated as authoritative.\n")

    for cached in all_cached:
        if cached.get("structured"):
            sections.append(format_structured_data(cached))
        elif cached.get("raw_text"):
            sections.append(format_raw_text(cached))

    return "\n".join(sections)


def build_prompt():
    """Build the full agent prompt."""
    # Load base prompt
    if BASE_PROMPT_FILE.exists():
        with open(BASE_PROMPT_FILE, "r", encoding="utf-8") as f:
            base = f.read()
    else:
        # First run: extract current prompt from Vocal Bridge
        print("Base prompt file not found. Extracting from Vocal Bridge...")
        result = subprocess.run(
            ["vb", "prompt", "show"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to get current prompt: {result.stderr}")

        # Parse output (skip "--- Greeting ---" and "--- System Prompt ---" headers)
        output = result.stdout
        prompt_start = output.find("--- System Prompt ---")
        if prompt_start >= 0:
            base = output[prompt_start + len("--- System Prompt ---"):].strip()
        else:
            base = output.strip()

        # Save as base template
        with open(BASE_PROMPT_FILE, "w", encoding="utf-8") as f:
            f.write(base)
        print(f"Saved base prompt to {BASE_PROMPT_FILE}")

    # Load client actions addition
    client_actions = ""
    if CLIENT_ACTIONS_FILE.exists():
        with open(CLIENT_ACTIONS_FILE, "r", encoding="utf-8") as f:
            client_actions = f.read()

    # Load scraped municipality data
    all_cached = get_all_cached_data()
    garbage_section = build_garbage_section(all_cached)

    # Combine
    # Check if base already contains Client Actions section
    if "## Client Actions" in base:
        # Base already has client actions, just append garbage data
        full_prompt = base + "\n" + garbage_section
    else:
        full_prompt = base + "\n" + client_actions + "\n" + garbage_section

    return full_prompt


def deploy_prompt():
    """Build and deploy prompt to Vocal Bridge."""
    prompt = build_prompt()

    print(f"Prompt size: {len(prompt)} chars")

    # Write to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(prompt)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["vb", "prompt", "set", "--file", tmp_path],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"Deployed! {result.stdout.strip()}")
        else:
            print(f"Deploy failed: {result.stderr}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return prompt


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python prompt_builder.py build    # Show built prompt (dry run)")
        print("  python prompt_builder.py deploy   # Build and deploy to Vocal Bridge")
        return

    cmd = sys.argv[1]

    if cmd == "build":
        prompt = build_prompt()
        print(prompt)
        print(f"\n--- Total: {len(prompt)} chars ---")

    elif cmd == "deploy":
        deploy_prompt()

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
