#!/usr/bin/env python
"""
Pre-build syntax checker for Python files.
Runs before PyInstaller to catch syntax errors early.
"""

import sys
import py_compile
from pathlib import Path
from typing import List, Tuple


def check_file(filepath: Path) -> Tuple[bool, str]:
    """
    Check a single Python file for syntax errors.

    Returns:
        (success, error_message)
    """
    try:
        py_compile.compile(str(filepath), doraise=True)
        return True, ""
    except py_compile.PyCompileError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Unexpected error: {e}"


def check_directory(
    directory: Path, exclude_dirs: List[str] = None
) -> List[Tuple[Path, str]]:
    """
    Check all Python files in a directory recursively.

    Returns:
        List of (filepath, error_message) for files with errors
    """
    if exclude_dirs is None:
        exclude_dirs = [
            "__pycache__",
            ".venv",
            "venv",
            "build",
            "dist",
            ".git",
            "installer",
        ]

    errors = []

    for py_file in directory.rglob("*.py"):
        # Skip excluded directories
        if any(excluded in py_file.parts for excluded in exclude_dirs):
            continue

        success, error = check_file(py_file)
        if not success:
            errors.append((py_file, error))

    return errors


def main():
    """Main entry point."""
    # Get project root (parent of scripts directory)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    print("=" * 60)
    print(" PYTHON SYNTAX CHECK")
    print("=" * 60)
    print(f"Checking: {project_root}")
    print()

    # Check all Python files
    errors = check_directory(project_root)

    if errors:
        print(f"❌ FOUND {len(errors)} SYNTAX ERROR(S):")
        print("-" * 60)
        for filepath, error in errors:
            relative_path = filepath.relative_to(project_root)
            print(f"\n📄 {relative_path}")
            print(f"   {error}")
        print()
        print("=" * 60)
        print(" BUILD ABORTED - Fix syntax errors first!")
        print("=" * 60)
        sys.exit(1)
    else:
        # Count checked files
        checked = sum(
            1
            for _ in project_root.rglob("*.py")
            if not any(
                x in _.parts
                for x in [
                    "__pycache__",
                    ".venv",
                    "venv",
                    "build",
                    "dist",
                    ".git",
                    "installer",
                ]
            )
        )
        print(f"✅ All {checked} Python files passed syntax check!")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    main()
