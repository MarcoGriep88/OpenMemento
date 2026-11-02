"""PyInstaller entry point; application services live in the installed package."""
from memento.app import main

if __name__ == "__main__":
    raise SystemExit(main())
