#!/usr/bin/env bash
set -euo pipefail

setup_root=/home/v100/mlcc-slurm-setup
backup_root=/var/backups/mlcc-slurm/$(date +%Y%m%d-%H%M%S)

exec > >(tee -a "$setup_root/install.log") 2>&1

printf '%s\n' 'Installing Slurm controller and compute service for the verified v100 host.'
install -d -m 0700 "$backup_root"
cp -a /etc/slurm "$backup_root/slurm"
dpkg-query -W slurm-client slurm-wlm-basic-plugins munge > "$backup_root/packages-before.txt"

apt-get install -y --no-install-recommends slurmctld slurmd slurm-client

install -d -o slurm -g slurm -m 0750 /var/lib/slurm/slurmctld
install -d -o root -g root -m 0755 /var/lib/slurm/slurmd
install -d -o slurm -g slurm -m 0750 /var/log/slurm
install -d -o root -g root -m 0755 /etc/slurm

cat > /etc/slurm/slurm.conf <<'SLURM_CONF'
ClusterName=mlcc-v100
SlurmctldHost=v100-System-Product-Name(192.168.110.35)
SlurmUser=slurm
SlurmdUser=root
AuthType=auth/munge
SlurmctldPort=6817
SlurmdPort=6818
StateSaveLocation=/var/lib/slurm/slurmctld
SlurmdSpoolDir=/var/lib/slurm/slurmd
SlurmctldPidFile=/run/slurmctld.pid
SlurmdPidFile=/run/slurmd.pid
SlurmctldLogFile=/var/log/slurm/slurmctld.log
SlurmdLogFile=/var/log/slurm/slurmd.log
SchedulerType=sched/backfill
PriorityType=priority/basic
MailProg=/bin/true
JobRequeue=0
SelectType=select/cons_tres
SelectTypeParameters=CR_Core_Memory
ProctrackType=proctrack/cgroup
TaskPlugin=task/cgroup,task/affinity
JobAcctGatherType=jobacct_gather/cgroup
JobAcctGatherFrequency=task=30
JobCompType=jobcomp/filetxt
JobCompLoc=/var/log/slurm/job-completion.log
AccountingStorageType=accounting_storage/none
GresTypes=gpu
ReturnToService=2
MinJobAge=86400
KillWait=30
SlurmctldTimeout=120
SlurmdTimeout=300
NodeName=v100 NodeAddr=192.168.110.35 NodeHostname=v100-System-Product-Name CPUs=16 Sockets=1 CoresPerSocket=8 ThreadsPerCore=2 RealMemory=27800 Gres=gpu:v100:4 State=UNKNOWN
PartitionName=cpu Nodes=v100 Default=YES MaxTime=1-00:00:00 State=UP OverSubscribe=NO
PartitionName=gpu Nodes=v100 Default=NO MaxTime=1-00:00:00 State=UP OverSubscribe=NO
SLURM_CONF

cat > /etc/slurm/gres.conf <<'GRES_CONF'
Name=gpu Type=v100 File=/dev/nvidia0
Name=gpu Type=v100 File=/dev/nvidia1
Name=gpu Type=v100 File=/dev/nvidia2
Name=gpu Type=v100 File=/dev/nvidia3
GRES_CONF

cat > /etc/slurm/cgroup.conf <<'CGROUP_CONF'
CgroupPlugin=cgroup/v2
ConstrainCores=yes
ConstrainDevices=yes
ConstrainRAMSpace=yes
CGROUP_CONF

chmod 0644 /etc/slurm/slurm.conf /etc/slurm/gres.conf /etc/slurm/cgroup.conf

systemctl enable munge
systemctl start munge
runuser -u v100 -- bash -c 'munge -n | unmunge'
/usr/sbin/slurmd -C
/usr/sbin/slurmd -G
systemctl enable slurmctld slurmd
systemctl start slurmctld
systemctl start slurmd
systemctl is-active munge slurmctld slurmd
scontrol ping
sinfo -N -l
printf '\nConfiguration backup: %s\n' "$backup_root"
printf '%s\n' 'Slurm services installed. CPU and CUDA job validation is the next step.'
date --iso-8601=seconds > "$setup_root/install-complete.txt"
