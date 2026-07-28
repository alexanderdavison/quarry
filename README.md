# Quarry

**Previously known as yt-to-obi.** A YouTube-to-Obsidian archiving pipeline.
Extracts metadata and transcripts from YouTube videos, writes permanent markdown
notes into the Obsidian vault, and seeds Honcho memory for future Hermes recall.

## Interfaces

- **WebUI:** http://192.168.1.21:5000 (service: quarryd)
- **CLI:** `quarry <youtube-url> [category]` on LXC 101
- **Compat alias:** `yt-to-obi` still works

## Pipeline

YouTube URL
  -> yt-dlp (metadata)
  -> youtube-transcript-api (transcript)
  -> Vault note at vault/<category>/youtube/<date>-<slug>.md
  -> Honcho conclusion (searchable by Hermes)

## Categories

sources, shared, homelab-wiki, personal-wiki -> hermes profile
real-estate -> hermes_real-estate
dental-msp  -> hermes_dental-msp
axiom-music -> hermes_axiom-music

## Source

Gitea at http://192.168.1.19:3000/ishmael/quarry
