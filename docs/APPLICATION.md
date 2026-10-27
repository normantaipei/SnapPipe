# Application Draft (English)

English text for the hackathon application form, condensed from [DESIGN.md](./DESIGN.md).
Adjust the wording to match the actual form fields.

## Project name

SnapPipe — real-time photo transmission and AI photo-desk for sports photojournalists

## Track / Theme

Indie Developer Track · Build for Your World

## One-liner

The camera's built-in FTP (or a $15 Raspberry Pi for cameras without it) plus Meta Muse Spark give any sports photographer a wire-agency workflow: the best frame of every burst, the players identified and a draft caption arrive at the photo desk within about 60 seconds of the shutter.

## Project idea

In sports news, speed wins. The first photo of the game-winning shot is the one that gets published. Big wire agencies have stadium networks, on-site editors and dedicated transmission gear. Freelancers, local outlets and student journalists don't. They wait until halftime or the final whistle to pull the card, cull thousands of near-identical burst frames (modern bodies shoot 20–30 fps), look up jersey numbers on a roster and type captions by hand.

SnapPipe moves that whole workflow to the moment of capture:

1. **Capture: three ingest modes, one pipeline.** (A, B) Cameras with built-in FTP all upload to one ingest endpoint on port 21. It uses explicit FTPS, so encrypted and plain-FTP cameras share the same port. Each camera has its own upload-only account, and a per-account policy decides whether plain FTP is accepted. Plain-FTP cameras can connect directly with per-game temporary passwords, or through a Raspberry Pi Zero 2 W on the local network that relays to the same port over FTPS. (C) Cameras without FTP are tethered over USB (libgphoto2), and the Pi streams JPEGs off the memory card. In every mode the Pi is a pure relay: no image processing, no local copies. The memory card is the only buffer, so on a poor or dropped network the frames wait on the card and are sent later. A clock-sync QR code shot before the game aligns camera time. RAW files are imported from the card after the game, deduplicated by SHA-256 against everything already sent.
2. **Ethical grading.** The server applies only global adjustments that photojournalism ethics allow (house-style LUT, exposure, white balance). It never alters content, and originals are stored unchanged under their SHA-256 hash.
3. **Meta AI, stage 1: burst comparison.** Muse Spark receives the whole burst at once and picks the decisive moment (ball contact, peak action, face in focus, emotion). It returns per-frame scores and issue flags as schema-validated JSON.
4. **Meta AI, stage 2: identification and caption.** For the selected frames, Muse Spark reads jersey numbers and team colors, matches them against the pre-loaded game roster and drafts the action sentence of an agency-style caption. Names may only come from the roster; low-confidence names are flagged for review; date, venue and credit are filled from templates, never generated.
5. **Editor desk.** A live web feed ranks bursts by score. The editor (or the photographer on a phone) confirms the caption and sends with one key. The photo goes out with full IPTC metadata (Headline, Caption, PersonInImage, Event, Urgency…) to FTP, CMS or social.

Target: shutter → photo on desk in under 10 s; shutter → publishable photo with draft caption in under 60 s (p50).

## Multi-camera by design

Sports shoots are multi-camera: a photographer often carries two bodies (frequently the same model), and remote cameras sit behind the backboard or goal. SnapPipe identifies every frame by **make + model + body serial number** from EXIF (or read over PTP by the Pi). The FTP account or Pi it arrived through is only a cross-check, so two identical bodies never get mixed up. Mismatches (e.g. two cameras configured with the same FTP account) are flagged, and unknown bodies are auto-registered instead of dropped.

- Filename collisions between identical bodies are impossible because storage is content-addressed.
- Burst grouping never crosses cameras.
- Clock offset is calibrated per body.
- Bursts from different cameras at the same instant are merged into multi-angle cards.
- Credits follow the per-game camera-to-photographer assignment.
- Exports are organized by camera, photographer or player, with time-ordered, collision-free filenames (`{corrected time to ms}_{camera}_{original name}`).

## Why me / Build for Your World

I shoot sports for news myself. Deadline pressure, burst culling and caption writing are my everyday problems, and I'll test SnapPipe at real games during the hackathon.

## How Meta AI is used

- **Multi-image reasoning.** A whole burst (up to 40 thumbnails) goes into one request so the model compares frames, which single-image aesthetic scorers can't do.
- **Structured outputs.** JSON Schemas map directly to IPTC fields and editor UI states.
- **Guardrails.** Names are validated against the roster, confidence thresholds trigger review, only the action sentence is AI-generated, and a human approves every publish.
- **Responsible AI.** No face recognition (identity comes from jersey number plus roster). Standard tier only, so news photos are not used for training. Originals and caption versions are kept so everything can be traced back.
- **Muse Code** is used throughout development.

## Feasibility

- 10-day plan: end-to-end path (capture → desk → AI ranking → caption → FTP delivery) by day 7; evaluation on my past games and a live stadium test on days 8–9.
- Estimated cost is about $4 per basketball game (3,000 frames), so the $150 credit covers roughly 35 games.
- The system degrades gracefully: if the AI is slow or down, the desk still works with time and sharpness ranking and manual captions.

## Evaluation

Labeled bursts from 3–5 of my past games. Metrics: Top-1/Top-3 agreement with my own picks, jersey-number accuracy, wrong-name rate, caption usable rate, end-to-end latency (p50/p95), and a mock-deadline test (time to send 5 publishable photos, manual vs. SnapPipe).

## Technical highlights

- Three ingest modes (FTPS and plain FTP sharing one port 21 endpoint, an optional Pi FTPS relay, and a Pi USB relay) feeding one content-addressed pipeline; the memory card is the buffer, so the Pi stores no photos.
- Idempotent, resumable chunked uploads that tolerate unreliable networks, newest frames first, with clock-offset correction and SHA-256 dedup on post-game card import.
- Priority job pipeline (FastAPI, Redis/arq, PostgreSQL) where the AI enriches photos asynchronously and never blocks the fast path.
- libvips/rawpy grading; exiftool IPTC/XMP writing.
- Real-time SSE editor desk (React) with keyboard-driven culling.
