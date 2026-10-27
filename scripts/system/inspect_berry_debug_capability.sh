#!/bin/bash
set -euo pipefail
MLCC_ABACUS=/home/v100/miniforge3/envs/abacus_env/bin/abacus
date -Is
gdb --version | head -n 1
file "$MLCC_ABACUS"
printf 'Core pattern: '
cat /proc/sys/kernel/core_pattern
printf 'Core limit: '
ulimit -c
printf 'Saved crash reports naming ABACUS: '
find /var/crash -maxdepth 1 -type f -name '*abacus*' -print
gdb -nx -batch -ex 'info functions unkdotp_G0' -ex 'info functions Berry_Phase' "$MLCC_ABACUS"
