from __future__ import annotations
import argparse
import os
import sys
import traceback
from pathlib import Path
from typing import Dict, Optional
def setup_environment() -> None:
    parent_dir = Path(__file__).parent.parent
    sys.path.insert(0, str(parent_dir))
    os.environ.setdefault('PYTHONUNBUFFERED', '1')
def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Nexus Core - Modular Platform')
    parser.add_argument('--config', type=str, help='Path to configuration file', default=None)
    parser.add_argument('--headless', action='store_true', help='Run in headless mode (no UI)', default=False)
    parser.add_argument('--debug', action='store_true', help='Enable debug mode', default=False)
    return parser.parse_args()
def start_ui(app_core: Any, args: argparse.Namespace) -> None:
    try:
        from nexus_core.ui.main_window import start_ui
        start_ui(app_core, args.debug)
    except ImportError as e:
        print(f'Error importing UI module: {e}')
        print('Running in headless mode.')
def main() -> int:
    setup_environment()
    args = parse_arguments()
    try:
        from nexus_core.core.app import ApplicationCore
        app_core = ApplicationCore(config_path=args.config)
        app_core.initialize()
        if not args.headless:
            start_ui(app_core, args)
        if args.headless:
            print('Nexus Core running in headless mode. Press Ctrl+C to exit.')
            try:
                import signal
                def signal_handler(sig, frame):
                    print('\nShutting down Nexus Core...')
                    app_core.shutdown()
                    sys.exit(0)
                signal.signal(signal.SIGINT, signal_handler)
                signal.signal(signal.SIGTERM, signal_handler)
                signal.pause()
            except KeyboardInterrupt:
                print('\nShutting down Nexus Core...')
                app_core.shutdown()
        return 0
    except Exception as e:
        print(f'Error starting Nexus Core: {e}')
        traceback.print_exc()
        return 1
if __name__ == '__main__':
    sys.exit(main())