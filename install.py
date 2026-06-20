#!/usr/bin/env python3
"""
Install Hermes Skill Precipitator.

Usage:
  python3 install.py                    # Install to ~/.hermes/scripts/
  python3 install.py --prefix /custom/path
  python3 install.py --cron             # Also register cron hook
  python3 install.py --test             # Run unit tests after install
"""
import argparse
import os
import shutil
import subprocess
import sys

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_SCRIPTS = os.path.join(REPO_DIR, "scripts")
SOURCE_ARCH = os.path.join(REPO_DIR, "ARCHITECTURE.md")

HERMES_HOME = os.path.expanduser("~/.hermes")
DEST_SCRIPTS = os.path.join(HERMES_HOME, "scripts")
DEST_CASES = os.path.join(HERMES_HOME, "agent", "cases")


def install(prefix: str = None):
    if prefix:
        dest = os.path.expanduser(prefix)
    else:
        dest = DEST_SCRIPTS
    
    os.makedirs(dest, exist_ok=True)
    
    # Source files
    src_files = [
        "skill_precipitator.py",
        "skill_precipitator_hook.py",
    ]
    src_dirs = ["precipitator"]
    
    for f in src_files:
        src = os.path.join(SOURCE_SCRIPTS, f)
        dst = os.path.join(dest, f)
        shutil.copy2(src, dst)
        print(f"  ✓ {dst}")
    
    for d in src_dirs:
        src = os.path.join(SOURCE_SCRIPTS, d)
        dst = os.path.join(dest, d)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"  ✓ {dst}/")
    
    # Ensure cases dir
    os.makedirs(DEST_CASES, exist_ok=True)
    
    print(f"\n✅ Installed to {dest}")
    return dest


def setup_cron():
    """Register the cron hook via Hermes CLI."""
    try:
        result = subprocess.run(
            ["hermes", "cron", "create",
             "--name", "skill-precipitator",
             "--schedule", "every 2h",
             "--script", "skill_precipitator_hook.py",
             "--no-agent"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            print("✅ Cron hook registered (every 2h)")
        else:
            print(f"⚠️  Cron setup: {result.stderr.strip()}")
            print("   Run manually: hermes cron create --name skill-precipitator \\")
            print("     --schedule 'every 2h' --script skill_precipitator_hook.py --no-agent")
    except FileNotFoundError:
        print("⚠️  Hermes CLI not found. Register cron manually (see README).")


def run_tests():
    """Run unit tests."""
    print("\nRunning tests...")
    result = subprocess.run(
        [sys.executable, "skill_precipitator.py", "test"],
        cwd=DEST_SCRIPTS,
        capture_output=True, text=True, timeout=30,
    )
    print(result.stdout)
    if result.returncode == 0:
        print("✅ All tests passed")
    else:
        print(f"❌ Tests failed:\n{result.stderr}")
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Install Hermes Skill Precipitator")
    parser.add_argument("--prefix", help="Custom install prefix (default: ~/.hermes/scripts/)")
    parser.add_argument("--cron", action="store_true", help="Also register cron hook")
    parser.add_argument("--test", action="store_true", help="Run unit tests after install")
    args = parser.parse_args()
    
    dest = install(prefix=args.prefix)
    
    if args.cron:
        setup_cron()
    
    if args.test:
        return run_tests()
    
    print(f"\nUsage:")
    print(f"  cd {dest}")
    print(f"  python3 skill_precipitator.py scan --limit 100")
    print(f"  python3 skill_precipitator.py forge --min-cases 3")
    print(f"  python3 skill_precipitator.py report")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
