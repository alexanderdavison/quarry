#!/usr/bin/env bash
# vault-honcho-seed — Seed Obsidian vault docs into each project's Honcho workspace
set -euo pipefail

VAULT="/mnt/obsidian-vault"
LOG="/tmp/vault-honcho-seed.log"

echo "=== Vault → Honcho seed $(date -u -Iseconds) ===" > "$LOG"

# Map project directories → target Hermes profile names (not Honcho workspace names)
declare -A PROFILES
PROFILES[homelab-wiki]="default"    # homelab is the default profile
PROFILES[real-estate]="real-estate"
PROFILES[dental-msp]="dental-msp"
PROFILES[axiom-music]="axiom-music"
PROFILES[ish-d]="ish-d"

seed_for_profile() {
    local file="$1"
    local profile="$2"
    local profile_flag=""
    [ "$profile" != "default" ] && profile_flag="--target-profile $profile"
    
    if hermes honcho $profile_flag identity "$file" >> "$LOG" 2>&1; then
        echo "  ✓ seeded: $file → $profile" >> "$LOG"
    else
        echo "  ✗ failed: $file → $profile" >> "$LOG"
    fi
}

for project_dir in "${!PROFILES[@]}"; do
    profile="${PROFILES[$project_dir]}"
    project_path="$VAULT/$project_dir"
    
    if [ ! -d "$project_path" ]; then
        echo "  [skip] $project_path not found" >> "$LOG"
        continue
    fi
    
    echo "--- $project_dir → profile '$profile' ---" >> "$LOG"
    
    # Seed project-level _index.md
    index_file="$project_path/_index.md"
    [ -f "$index_file" ] && seed_for_profile "$index_file" "$profile"
    
    # Seed all .md files in the project directory
    find "$project_path" -maxdepth 2 -name '*.md' -not -name '_index.md' | sort | while read -r doc; do
        seed_for_profile "$doc" "$profile"
    done
done

# Also seed system-level docs into default profile
echo "--- system docs → default ---" >> "$LOG"
for sysdoc in "_index.md" "SCHEMA.md" "topology.md"; do
    sysfile="$VAULT/$sysdoc"
    [ -f "$sysfile" ] && seed_for_profile "$sysfile" "default"
done

echo "" >> "$LOG"
echo "Done. Total docs seeded: $(grep -c '✓ seeded' "$LOG")" >> "$LOG"
grep '✓\|✗\|Done\|===' "$LOG"
