#include <cuda_runtime.h>
#include <cstdio>
#include <unistd.h>
#include <vector>

__global__ void fill_values(float* values, int value_count) {
    int value_index = blockIdx.x * blockDim.x + threadIdx.x;
    if (value_index < value_count) {
        values[value_index] = static_cast<float>(value_index % 97);
    }
}

int main() {
    int device_count = 0;
    cudaError_t cuda_status = cudaGetDeviceCount(&device_count);
    if (cuda_status != cudaSuccess || device_count != 1) {
        std::fprintf(stderr, "CUDA device count=%d, status=%s\n", device_count, cudaGetErrorString(cuda_status));
        return 1;
    }

    char pci_bus_id[32] = {};
    cuda_status = cudaDeviceGetPCIBusId(pci_bus_id, sizeof(pci_bus_id), 0);
    if (cuda_status != cudaSuccess) {
        std::fprintf(stderr, "%s\n", cudaGetErrorString(cuda_status));
        return 2;
    }

    const int value_count = 1048576;
    std::vector<float> host_values(value_count);
    float* device_values = nullptr;
    cuda_status = cudaMalloc(&device_values, value_count * sizeof(float));
    if (cuda_status != cudaSuccess) {
        std::fprintf(stderr, "%s\n", cudaGetErrorString(cuda_status));
        return 3;
    }

    fill_values<<<value_count / 256, 256>>>(device_values, value_count);
    cuda_status = cudaDeviceSynchronize();
    if (cuda_status != cudaSuccess) {
        std::fprintf(stderr, "%s\n", cudaGetErrorString(cuda_status));
        return 4;
    }

    cuda_status = cudaMemcpy(host_values.data(), device_values, value_count * sizeof(float), cudaMemcpyDeviceToHost);
    if (cuda_status != cudaSuccess) {
        std::fprintf(stderr, "%s\n", cudaGetErrorString(cuda_status));
        return 5;
    }

    for (int value_index = 0; value_index < value_count; ++value_index) {
        if (host_values[value_index] != static_cast<float>(value_index % 97)) {
            std::fprintf(stderr, "Kernel result mismatch at %d\n", value_index);
            return 6;
        }
    }

    std::printf("PASS CUDA_KERNEL=verified VISIBLE_GPUS=%d PCI_BUS_ID=%s PID=%d\n", device_count, pci_bus_id, getpid());
    std::fflush(stdout);
    sleep(30);
    cuda_status = cudaFree(device_values);
    return cuda_status == cudaSuccess ? 0 : 7;
}
