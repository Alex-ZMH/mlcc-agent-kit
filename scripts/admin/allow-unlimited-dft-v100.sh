#!/usr/bin/env bash
# Apply as administrator on v100. No calculation or service restart is launched.
set -euo pipefail

config=/etc/slurm/slurm.conf
backup="${config}.before-unlimited-dft-$(date +%Y%m%d-%H%M%S)"
cp -a "$config" "$backup"
# Keep the prior one-day default for jobs without an explicit time request.
# Future DFT jobs explicitly request --time=0; other jobs retain their budgets.
sed -i -E '/^PartitionName=(cpu|gpu)[[:space:]]/ { s/MaxTime=[^[:space:]]+/MaxTime=UNLIMITED/; /DefaultTime=/! s/$/ DefaultTime=1-00:00:00/; }' "$config"
scontrol reconfigure
scontrol show partition cpu
scontrol show partition gpu
printf 'Previous configuration: %s\n' "$backup"
