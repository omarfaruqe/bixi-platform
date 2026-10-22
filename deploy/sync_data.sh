#!/usr/bin/env bash
# Copy the processed results the server needs (about 5 MB) from this machine to the server.
#
#   deploy/sync_data.sh USER@103.99.176.180 [remote project dir, default ~/bixi-platform]
#
# Run it from the project folder on the Mac, after the pipeline steps that changed the files.
# One ssh session: the files travel as a tar stream, land under data/processed/ on the server and
# are made world-readable, because the containers run as an unprivileged user.
set -euo pipefail

target="${1:?usage: deploy/sync_data.sh USER@HOST [remote project dir]}"
remote_dir="${2:-~/bixi-platform}"
cd "$(dirname "$0")/../data/processed"

files=(
  hourly_station.parquet
  model_results/metrics_overall.parquet
  model_results/errors_by_hour.parquet
  model_results/errors_by_station.parquet
  model_results/importance.parquet
  forecasts/holdout-2025.parquet
  forecasts/holdout-2025.json
  rebalancing/summary.parquet
  rebalancing/stops.parquet
  rebalancing/inventory.parquet
  rebalancing/assumptions.json
)
present=()
for f in "${files[@]}"; do
  if [[ -f "$f" ]]; then present+=("$f"); else echo "skipped (not built yet): $f"; fi
done
[[ ${#present[@]} -gt 0 ]] || { echo "nothing to copy"; exit 1; }

export COPYFILE_DISABLE=1  # macOS: no ._ metadata files in the archive
tar -czf - "${present[@]}" | ssh "$target" \
  "mkdir -p $remote_dir/data/processed && tar -xzf - -C $remote_dir/data/processed \
   && chmod -R a+rX $remote_dir/data/processed"
echo "copied ${#present[@]} files to $target:$remote_dir/data/processed"
