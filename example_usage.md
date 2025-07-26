# Example Usage Walkthrough

This guide shows a complete example of using the cloud scheduler system.

## Step 1: Find Cheapest Instances

```bash
python find_cheapest_instance.py
```

**Output:**
```
====================================================================================================
Provider | Instance Type        | Region         | vCPUs  | RAM (GB) | $/hour     | $/core/hr 
====================================================================================================
AWS      | m5.4xlarge          | us-east-1      | 16     | 64       | $0.4000    | $0.0250   
GCP      | n2-standard-16      | us-central1    | 16     | 64       | $0.4200    | $0.0263   
Azure    | Standard_D16s_v5    | eastus         | 16     | 64       | $0.4400    | $0.0275   
AWS      | r5.4xlarge          | us-west-2      | 16     | 128      | $0.4500    | $0.0281   
...

====================================================================================================
INSTANCE SELECTION
====================================================================================================

Option 1 - Cheapest per-core instance:
  Provider: AWS
  Instance: m5.4xlarge
  Region: us-east-1
  vCPUs: 16
  RAM: 64 GB
  Price: $0.4000/hour ($0.0250/core/hour)

Option 2 - Cheapest overall instance:
  Provider: AWS
  Instance: m5.2xlarge
  Region: us-east-1
  vCPUs: 8
  RAM: 32 GB
  Price: $0.2000/hour ($0.0250/core/hour)

Option 3 - Higher memory alternative:
  Provider: AWS
  Instance: r5.4xlarge
  Region: us-west-2
  vCPUs: 16
  RAM: 128 GB (+64 GB)
  Price: $0.4500/hour ($0.0281/core/hour)
  Additional cost: +$0.0500/hour
  (100% more memory for 13% more cost)

Option 4 - Abort

Select option (1, 2, 3, 4): 3

Selected: AWS r5.4xlarge in us-west-2 at $0.4500/hour

Selected instance saved as index 0 in spot_prices.json
Top 20 results saved to spot_prices.json
```

## Step 2: Prepare Job Files

Create a directory with your calculation files:

```bash
mkdir water_dimer_calc
cd water_dimer_calc

# Add your SHCI executable and input files
cp /path/to/shci_program .
cat > input.inp << EOF
epsilon1 1e-6
epsilon2 1e-8
targetError 1e-5
dE 1e-6
maxIter 20
nPTiter 2
doRDM
EOF
```

## Step 3: Submit Job

```bash
cd ..  # Back to main directory
python cloud_run.py water_dimer_calc \
  --s3-bucket my-shci-jobs \
  --from-spot-prices \
  --basis aug-cc-pVTZ \
  --gdrive-path "water_dimer_$(date +%Y%m%d)"
```

**Output:**
```
INFO - Uploading files from water_dimer_calc to s3://my-shci-jobs/a1b2c3d4/input/
INFO - Uploaded 3 files to S3
INFO - Job metadata saved to s3://my-shci-jobs/a1b2c3d4/metadata.json
INFO - Selected from spot_prices.json: AWS r5.4xlarge in us-west-2 at $0.4500/hour
INFO - Instance launched successfully: i-0123456789abcdef0
INFO - Public IP: 54.123.45.67

Job a1b2c3d4 launched successfully!
Input files: s3://my-shci-jobs/a1b2c3d4/input/
Results will sync to: gdrive:water_dimer_20241126

Monitor progress in Google Drive (syncs every 5 minutes)
```

## Step 4: Monitor Progress

Check your Google Drive folder `water_dimer_20241126` for:

- `calculation.log` - Real-time calculation progress
- `calculation_summary.json` - Structured results
- `shci.out` - SHCI program output
- `results.txt` - Human-readable summary

Files sync every 5 minutes. The instance will terminate automatically when complete.

## Advanced Usage

### Custom Configuration

```bash
python cloud_run.py my_job \
  --s3-bucket my-shci-jobs \
  --provider AWS \
  --instance r7i.8xlarge \
  --region us-east-1 \
  --basis cc-pVTZ \
  --shci-executable "./custom_shci" \
  --exclude "*.bak" "debug_*"
```

### Non-Interactive Mode

```bash
python find_cheapest_instance.py --no-interactive
python cloud_run.py my_job --s3-bucket my-shci-jobs --index 0
```

This automatically uses the cheapest instance without prompting.