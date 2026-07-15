# yt → obi

**A YouTube scraping pipeline that preserves knowledge in your Obsidian vault.**

YouTube is the largest library of human knowledge ever built — tutorials, conference talks, interviews, deep dives, reviews, and cultural ephemera. But it's a terrible library. Videos disappear, channels get deleted, algorithms decide what you see, and search is noisy. If you watched something valuable and want to keep it, reference it, or build on it, you need a copy — not of the video, but of the *information* in it.

`yt-to-obi` takes a YouTube URL, extracts the metadata (title, channel, date, duration, description), fetches the full transcript with timestamps, and writes it all as a clean markdown note directly into your Obsidian vault. Searchable. Linkable. Permanent.

---

## Why this exists

### The problem

1. **YouTube is a consumption engine, not a reference library.** You watch a deep-dive tutorial on Kubernetes networking, a conference talk on the future of LLMs, or a market analysis video for a property market you're researching. Six months later, you need that information. Where is it? Buried in your watch history, behind a search that prioritizes recency and virality over relevance. Or the video was taken down.

2. **Information you can't search is information you don't have.** If you took notes in a separate app, they're disconnected from each other. If you didn't take notes, the information is trapped inside a video. You can't grep a video. You can't link from a video to your other notes. You can't reference it in a project doc or a research brief.

3. **YouTube is ephemeral.** Channels are deleted. Uploads are made private. Creators move on. If you didn't capture the information when you had access, you may not have it later.

### The solution

`yt-to-obi` makes YouTube content *permanent and portable* by extracting the information layer — title, metadata, description, and full transcript — and writing it as a standard markdown file in your Obsidian vault. Once it's in your vault:

- **It's searchable.** Obsidian's search and graph view work across all your notes, including scraped transcripts.
- **It's linkable.** `[[wikilinks]]` connect scraped content to your projects, research, meeting notes, and ideas.
- **It's yours.** Your vault syncs via Syncthing, backs up to your storage, and lives under your control.
- **It's organized by profile.** A real-estate video goes into `real-estate/youtube/`, a homelab tutorial goes into `homelab-wiki/youtube/`, a venue management talk goes into `axiom-music/youtube/`. The vault structure already handles this; `yt-to-obi` respects it.

---

## Use cases

### 1. Technical research (homelab, software, infrastructure)

You find an hour-long conference talk or a detailed tutorial on a tool you're evaluating. You scrape it:

```
yt-to-obi "https://youtube.com/watch?v=..." homelab-wiki
```

The talk now lives as a note in `homelab-wiki/youtube/` with the full transcript, timestamps, and speaker/source attribution. Next month when you're debugging that tool, `grep transcript` across your vault finds the exact timestamp where the speaker addressed your problem.

### 2. Market research (real estate, investing)

You watch a property market analysis, a rent-vs-buy breakdown, or an interview with a local agent. You scrape it into the real-estate profile:

```
yt-to-obi "https://youtube.com/watch?v=..." real-estate
```

The note lands in `real-estate/youtube/`, linkable from your deal sheets, property notes, and research documents. The timestamped transcript lets you jump to the exact data point months later.

### 3. Professional development (dental MSP, healthcare IT)

A HIPAA compliance webinar, a dental practice software review, a cybersecurity best-practices talk. Scrape it into dental-msp:

```
yt-to-obi "https://youtube.com/watch?v=..." dental-msp
```

Now it lives alongside your SOPs, vendor notes, and infrastructure docs — searchable from the same vault where you manage your practice.

### 4. Venue & event management (axiom music)

Booking strategies, live sound tutorials, marketing playbooks, artist management advice. Scrape it into axiom-music:

```
yt-to-obi "https://youtube.com/watch?v=..." axiom-music
```

Permanent reference for a field where institutional knowledge is often oral and scattered.

### 5. Personal knowledge management

Any video you watch and want to remember — book summaries, philosophy lectures, language lessons, cooking techniques, travel guides. Scrape it into `personal-wiki` or `sources`:

```
yt-to-obi "https://youtube.com/watch?v=..." personal-wiki
```

Your vault becomes a second brain that includes the best of what YouTube has to offer, without the YouTube.

---

## How it works

### Pipeline

```
YouTube URL
    │
    ▼
yt-dlp (metadata extraction)
    │  ├── title, channel, upload date
    │  ├── duration, view count
    │  └── description
    │
    ▼
youtube-transcript-api (transcript fetch)
    │  └── timestamped text (auto-captions or manual subs)
    │
    ▼
Note writer
    │  ├── YAML frontmatter (title, source, url, channel, date, duration, views)
    │  ├── Markdown body with all metadata
    │  └── Full transcript with MM:SS timestamps
    │
    ▼
Obsidian vault
    └── /<category>/youtube/<date>-<slug>.md
```

### Two interfaces

**CLI** — for scripting, cron jobs, and terminal users:

```bash
yt-to-obi "https://youtube.com/watch?v=dQw4w9WgXcQ" sources
```

**WebUI** — for quick ad-hoc scrapes in the browser:

A minimal dark-themed interface (inspired by cobalt.tools) at `http://192.168.1.21:5000`. Paste a URL, pick a category, hit scrape. The result shows you where the note landed with a link to view it.

The WebUI includes a settings panel with toggles for transcript and description inclusion, a debug/info-for-nerds section showing service status and version info, and a test-scrape button for verifying the pipeline.

---

## Output format

```markdown
---
title: "Video Title"
source: youtube
url: "https://youtube.com/watch?v=..."
channel: "Channel Name"
date: "2026-07-14"
duration: "12:34"
views: 1234567
---

# Video Title

**Channel:** Channel Name
**Date:** 2026-07-14
**Duration:** 12:34
**Views:** 1,234,567
**URL:** [Link](https://youtube.com/watch?v=...)

## Description

(Full video description text, up to 2000 characters)

## Transcript

00:00 Introduction — speaker sets up the topic
01:23 Background — context and prior work
05:45 Core content — the main discussion
...
```

---

## Future directions

- **Channel subscriptions** — cron-driven auto-scrape of specified channels (detect new uploads, scrape automatically)
- **Instagram support** — extend the pipeline for Instagram posts/reels using gallery-dl
- **WebUI improvements** — schedule management, channel watchlist, inline transcript preview
- **Multi-language transcripts** — configurable language preference per scrape

---

## Architecture

| Component | Technology |
|-----------|-----------|
| Metadata extraction | yt-dlp 2026.07.04 |
| Transcript fetching | youtube-transcript-api 1.2.4 |
| Web framework | Flask 3.1.3 |
| Runtime environment | Python 3.12 (Debian 12 LXC) |
| Host | LXC 101 (ytdlp-scraper) on pve-m910-01 |
| Vault storage | Obsidian vault via NFS bind mount |
| Source control | Gitea at 192.168.1.19:3000/ishmael/yt-to-obi |
