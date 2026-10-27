#include <mpi.h>
#include <cuda_runtime.h>
#include <sched.h>
#include <cstdio>
#include <cstdlib>

static void cuda_call(cudaError_t result) {
    if (result != cudaSuccess) {
        std::fprintf(stderr, "CUDA error: %s\n", cudaGetErrorString(result));
        MPI_Abort(MPI_COMM_WORLD, static_cast<int>(result));
    }
}

int main(int argc, char **argv) {
    MPI_Init(&argc, &argv);
    int rank, size, host_length;
    char host[MPI_MAX_PROCESSOR_NAME];
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);
    MPI_Get_processor_name(host, &host_length);
    int value = rank + 1, host_sum = -1;
    MPI_Allreduce(&value, &host_sum, 1, MPI_INT, MPI_SUM, MPI_COMM_WORLD);
    int expected = size * (size + 1) / 2;
    cpu_set_t mask;
    CPU_ZERO(&mask);
    int affinity_status = sched_getaffinity(0, sizeof(mask), &mask);
    if (affinity_status != 0) {
        std::perror("sched_getaffinity");
        MPI_Abort(MPI_COMM_WORLD, 21);
    }
    int local_rank = std::atoi(std::getenv("OMPI_COMM_WORLD_LOCAL_RANK"));
    int count;
    cuda_call(cudaGetDeviceCount(&count));
    cuda_call(cudaSetDevice(local_rank));
    char pci[32];
    cuda_call(cudaDeviceGetPCIBusId(pci, sizeof(pci), local_rank));
    int *device_send, *device_receive;
    cuda_call(cudaMalloc(reinterpret_cast<void **>(&device_send), sizeof(int)));
    cuda_call(cudaMalloc(reinterpret_cast<void **>(&device_receive), sizeof(int)));
    cuda_call(cudaMemcpy(device_send, &value, sizeof(int), cudaMemcpyHostToDevice));
    MPI_Allreduce(device_send, device_receive, 1, MPI_INT, MPI_SUM, MPI_COMM_WORLD);
    int device_sum = -1;
    cuda_call(cudaMemcpy(&device_sum, device_receive, sizeof(int), cudaMemcpyDeviceToHost));
    cuda_call(cudaDeviceSynchronize());
    for (int turn = 0; turn < size; ++turn) {
        MPI_Barrier(MPI_COMM_WORLD);
        if (turn == rank) {
            std::printf("rank=%d size=%d host=%s local_rank=%d visible_gpus=%d pci=%s host_sum=%d device_sum=%d expected=%d affinity=",
                        rank, size, host, local_rank, count, pci, host_sum, device_sum, expected);
            for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) {
                if (CPU_ISSET(cpu, &mask)) std::printf("%d,", cpu);
            }
            std::printf("\n");
            std::fflush(stdout);
        }
    }
    cuda_call(cudaFree(device_send));
    cuda_call(cudaFree(device_receive));
    int failed = host_sum != expected || device_sum != expected;
    MPI_Finalize();
    return failed ? 22 : 0;
}
