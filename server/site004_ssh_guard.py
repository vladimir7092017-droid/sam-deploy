#!/usr/bin/env python3
"""Install root-owned as forced-command for one SITE-004-only SSH public key.

No shell, arguments, arbitrary docroot, or caller-provided manifest are accepted.
The private key belongs ONLY in protected GitHub Environment Secrets.
"""
import os
import sys

COMMANDS = {
    'site004-inventory': 'inventory',
    'site004-prepare': 'prepare',
    'site004-publish': 'publish',
    'site004-rollback': 'rollback',
}

if __name__ == '__main__':
    if os.geteuid() == 0 or os.getuid() == 0:
        sys.exit('The release command must run as site-deploy, never root')
    operation = COMMANDS.get(os.environ.get('SSH_ORIGINAL_COMMAND', ''))
    if operation is None:
        sys.exit('Only four fixed SITE-004 operations are allowed')
    os.execv('/usr/bin/python3',
             ['/usr/bin/python3', '/usr/local/libexec/site004_release.py', operation])
