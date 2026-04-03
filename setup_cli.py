"""
setup_cli.py — Install the `axon` CLI command on Windows.

Run once:  python setup_cli.py
Then open a new terminal and `axon` works from anywhere.
"""

import os
import subprocess
import sys


def main() -> None:
    project_root = os.path.dirname(os.path.abspath(__file__))
    bat_path = os.path.join(project_root, "axon.bat")

    # Verify axon.bat exists
    if not os.path.isfile(bat_path):
        print(f"❌ axon.bat not found at {bat_path}")
        sys.exit(1)

    # Add project root to the user PATH (permanent, survives restarts)
    print(f"📂 Project root: {project_root}")
    print("🔧 Adding to user PATH...")

    # Read current user PATH, append if not already present
    ps_check = subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            '[Environment]::GetEnvironmentVariable("PATH", "User")',
        ],
        capture_output=True,
        text=True,
    )
    current_path = ps_check.stdout.strip()

    if project_root.lower() in current_path.lower():
        print("   Already in PATH — skipping.")
    else:
        new_path = current_path.rstrip(";") + ";" + project_root
        subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f'[Environment]::SetEnvironmentVariable("PATH", "{new_path}", "User")',
            ],
            check=True,
        )
        print("   ✅ Added to user PATH.")

    print()
    print("✅ Axon CLI installed!")
    print("   Run 'axon' from any terminal to start.")
    print("   You may need to restart your terminal for PATH changes to take effect.")


if __name__ == "__main__":
    main()
