#!/bin/bash
set -e
date --iso-8601=seconds
hostname
id
scontrol ping
sinfo -N -l
squeue -o "%.18i %.9P %.25j %.8u %.2t %.10M %.6D %R"
nvidia-smi --query-gpu=index,name,memory.total,memory.used --format=csv
df -h /home/v100
scontrol show config
scontrol show node v100
srun --mpi=list
source /home/v100/projects/mlcc/configs/vasp-nvhpc-env.sh
mpirun --version
ldd /opt/vasp/vasp_std
ompi_info --parsable --all | grep -E "ompi:version:full|mca:pmix:pmix3x:|mca:plm:slurm:|mca:ras:slurm:|opal_built_with_cuda_support"
