#!/bin/sh
# Install as a root-owned file and pass the three roots as fixed arguments in
# the restricted authorized_keys command, never as SSH client input.
set -eu
[ "$(id -un)" = site-deploy ]
[ "$(id -u)" -ne 0 ]
[ "${SSH_ORIGINAL_COMMAND:-}" = check-smartangar ]
[ "$#" -eq 3 ]
for root do
  [ -d "$root" ] && [ -r "$root" ] && [ -x "$root" ] || {
    echo 'A required document root is not readable and traversable.' >&2
    exit 1
  }
done
printf '%s\n' smartangar-ssh-check-ok
