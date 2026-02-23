#!/usr/bin/env python3
"""Thin wrapper to run inbox-monitor.sh via launchd.

macOS TCC blocks /bin/bash (SIP-protected) from accessing ~/Documents/
when launched by launchd. Homebrew python3 is not SIP-restricted and
can access these paths, so we use subprocess to invoke the bash script.
"""

import os
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(__file__), "inbox-monitor.sh")

result = subprocess.run(
    ["/bin/bash", SCRIPT] + sys.argv[1:],
    cwd=os.path.dirname(os.path.dirname(__file__)),
    env={
        "HOME": os.environ.get("HOME", os.path.expanduser("~")),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"),
    },
)
sys.exit(result.returncode)
