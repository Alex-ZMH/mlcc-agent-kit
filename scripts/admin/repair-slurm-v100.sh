#!/usr/bin/env bash
set -euo pipefail

cp -a /etc/slurm/slurm.conf /var/backups/mlcc-slurm/slurm.conf.before-priority-fix
printf '\nPriorityType=priority/basic\nMailProg=/bin/true\nJobRequeue=0\n' >> /etc/slurm/slurm.conf
systemctl restart slurmctld
systemctl is-active slurmctld slurmd
scontrol ping
scontrol show config | grep -E 'PriorityType|JobRequeue|MailProg'
date --iso-8601=seconds > /home/v100/mlcc-slurm-setup/priority-fix-complete.txt
