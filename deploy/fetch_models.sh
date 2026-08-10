#!/usr/bin/env bash
# Fetch large model weights that are too big for GitHub (>100 MB) from Google Drive.
#
# WHY THIS EXISTS: the deployed LULC models are all tiny *linear* joblibs (a few KB — they replay as
# Earth-Engine band math), so NONE of them need this today and GitHub holds them fine. This is the
# ready-made hook for a genuinely large future model (the biomass RF ~528 MB, a learned segmentation
# net, drone-RGB DINO embeddings, …): upload the weight to Google Drive, make it link-shareable, add
# its file-id + destination to MODELS below, and this script pulls it into data/ on a fresh box.
#
# Run:  bash deploy/fetch_models.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# each entry: "<google_drive_file_id>  <dest_path_relative_to_repo>"
MODELS=(
  # "1AbCdEfGhIjKlMnOpQrStUv  data/refine/biomass_aez8.joblib"
)

if [ ${#MODELS[@]} -eq 0 ]; then
  echo "No large models registered — nothing to fetch (all current models ship in git / the image)."
  exit 0
fi

command -v gdown >/dev/null 2>&1 || pip install --quiet gdown
for entry in "${MODELS[@]}"; do
  id="${entry%% *}"; dest="${entry##* }"
  if [ -f "$dest" ]; then echo "have  $dest"; continue; fi
  mkdir -p "$(dirname "$dest")"
  echo "fetch $dest  <- drive:$id"
  gdown "https://drive.google.com/uc?id=$id" -O "$dest"
done
echo "done"
