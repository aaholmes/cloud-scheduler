# **Recommended Hardware Range for Preliminary Calculations**

For your preliminary calculations on the water dimer with `aug-cc-pVDZ` and `aug-cc-pVTZ`, you want a balance between speed and cost. The key is to prioritize memory, as the SHCI perturbative stage's efficiency scales super-linearly with available RAM.[1]

* **vCPU Range:** **16 to 32 vCPUs**. This provides enough parallel processing power to complete the variational stage quickly.
* **RAM Range:** **64 to 256 GiB**. Aim for a high memory-to-CPU ratio (at least 4:1, but 8:1 is ideal). An instance like the AWS `r7i.8xlarge` (32 vCPUs, 256 GiB RAM) is a perfect example of a target machine.