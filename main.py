"""Run the planner's command-line interface: ``python main.py plan PROFILE`` (see ``optimizer.cli``)."""

import sys

from optimizer.cli import main

if __name__ == "__main__":
    sys.exit(main())
