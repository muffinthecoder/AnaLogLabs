# sample_logs/

This folder contains **anonymised, synthetic sample log files** used for development and testing purposes only.

## Purpose
These files allow developers to test the AnaLog Labs parser, normaliser, filter, and visualisation components without needing access to real forensic log data.

## Rules
- **Never commit real log files** to this repository
- All files in this folder must be synthetic or fully anonymised
- Real investigation data must remain on the investigator's local machine at all times
- If you need to test with real data, load it locally and ensure it is listed in `.gitignore`

## File naming convention
```
sample_<log_type>_<region>_<version>.csv
e.g.
sample_interactive_signin_dubai_v1.csv
sample_mupc_perth_v1.csv
sample_wlc_singapore_v1.csv
```
