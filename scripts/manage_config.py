#!/usr/bin/env python3
"""
Configuration management CLI for AsterDex Funding Bot
"""
import sys
import json
import argparse
from config import ConfigManager, BotConfig

def show_config(config_mgr: ConfigManager):
    """Show current configuration"""
    print("=== Current Configuration ===")
    config_mgr.print_config()

    print(f"\nConfiguration file: {config_mgr.config_file}")
    print("Environment variables (FUNDING_*, ASTERDEX_*) take precedence over file settings")

def update_config(config_mgr: ConfigManager, updates: dict):
    """Update configuration with new values"""
    try:
        # Load current config
        current = config_mgr.load_config()
        current_dict = current.to_dict()

        # Apply updates
        for key, value in updates.items():
            if hasattr(current, key):
                current_dict[key] = value
                print(f"Updated {key}: {value}")
            else:
                print(f"Warning: Unknown config key '{key}' ignored")

        # Create and save new config
        new_config = BotConfig(**current_dict)

        if config_mgr.save_config(new_config):
            print("✅ Configuration saved successfully!")
            return True
        else:
            print("❌ Failed to save configuration")
            return False

    except Exception as e:
        print(f"❌ Error updating configuration: {e}")
        return False

def set_from_json(config_mgr: ConfigManager, json_str: str):
    """Set configuration from JSON string"""
    try:
        config_dict = json.loads(json_str)
        return update_config(config_mgr, config_dict)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}")
        return False

def create_example(config_mgr: ConfigManager, filename: str = None):
    """Create example configuration file"""
    filename = filename or "bot_config.example.json"
    if config_mgr.create_example_config(filename):
        print(f"✅ Example configuration created: {filename}")
        return True
    else:
        print(f"❌ Failed to create example configuration")
        return False

def main():
    parser = argparse.ArgumentParser(description="Manage AsterDex Funding Bot configuration")
    parser.add_argument(
        "--config-file",
        "-c",
        help="Configuration file path",
        default="samples/bot_config.json",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Show command
    subparsers.add_parser("show", help="Show current configuration")

    # Set command
    set_parser = subparsers.add_parser("set", help="Set configuration values")
    set_parser.add_argument("key", help="Configuration key")
    set_parser.add_argument("value", help="Configuration value")

    # Update command
    update_parser = subparsers.add_parser("update", help="Update multiple configuration values")
    update_parser.add_argument("updates", help="JSON object with updates", nargs="?")

    # Example command
    example_parser = subparsers.add_parser("example", help="Create example configuration file")
    example_parser.add_argument("--filename", "-f", help="Output filename", default="bot_config.example.json")

    # JSON command
    json_parser = subparsers.add_parser("json", help="Set configuration from JSON")
    json_parser.add_argument("json_config", help="JSON configuration string")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Initialize config manager
    config_mgr = ConfigManager(args.config_file)

    if args.command == "show":
        show_config(config_mgr)

    elif args.command == "set":
        success = update_config(config_mgr, {args.key: args.value})
        return 0 if success else 1

    elif args.command == "update":
        if args.updates:
            success = set_from_json(config_mgr, args.updates)
        else:
            print("Please provide updates as JSON")
            print('Example: python scripts/manage_config.py update \'{"capital": "200", "batch_quote": "20"}\'')
            return 1
        return 0 if success else 1

    elif args.command == "example":
        success = create_example(config_mgr, args.filename)
        return 0 if success else 1

    elif args.command == "json":
        success = set_from_json(config_mgr, args.json_config)
        return 0 if success else 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
