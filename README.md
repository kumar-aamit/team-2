# Machine Downtime Log

A real-time tracker for manufacturing-floor machine stoppages that automatically logs downtime tickets from a live event stream, displays a live dashboard, and integrates with a local LLM for event classification—all running on-premises for secure, low-latency operation.

## Features

- **Automatic Downtime Logging**: Consumes a live event stream (simulated or real) and automatically creates downtime tickets with machine ID, type, start/end times, and downtime minutes.
- **Live Dashboard**: Shows total downtime minutes today across all machines and highlights the worst-performing machine by downtime.
- **Running Event List**: Displays a chronological list of recent events in the UI.
- **Manual Notes**: Allows operators to add free-text notes to each event.
- **On-Screen Latency Indicator**: Shows event-to-display latency in milliseconds to prove the local, no-cloud-round-trip advantage.
- **On-Prem Secure Icon**: Visual indicator that data never leaves the premises.
- **LLM Integration**: Calls a locally hosted NVIDIA Nemotron model (via vLLM with OpenAI-compatible API) to classify each event's reason category and severity, with graceful fallback.
- **LLM Reachability Indicator**: UI indicator showing whether the LLM server is reachable.
- **Built‑In Event Simulator**: Toggleable via `SIMULATOR_ENABLED` to generate realistic stoppage events for testing and demos.
- **SQLite Persistence**: Stores downtime events in a SQLite database persisted to a volume at `/data`.
- **Dockerized**: Runs as a single container (or via docker‑compose) on Ubuntu using a slim Python base image.
- **GitHub Container Registry**: Image is built and pushed to GHCR via GitHub Actions.

## Architecture

- **Backend**: Python 3.10 with FastAPI.
- **Frontend**: Single‑page HTML/JavaScript served directly by the FastAPI app (no separate build step).
- **Real‑time Updates**: Server‑Sent Events (SSE) from backend to browser.
- **Database**: SQLite (file stored in `/data/downtime.db`).
- **Event Source**: Built‑in simulator (toggleable) or hook for external stream.
- **LLM Client**: Async HTTP client to a local vLLM server; defensive parsing with fallback.
- **Deployment**: Docker image (`ghcr.io/pl247/team-2`) orchestrated by `docker-compose.yml`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_PORT` | `8742` | Port the application listens on. On startup, the app checks if this port is free; if not, it prints an error and exits. |
| `LLM_BASE_URL` | `http://198.18.5.11:8000/v1` | Base URL of the vLLM server offering an OpenAI‑compatible API. |
| `LLM_MODEL` | `/ai/models/NVIDIA/Nemotron-3-120B/` | Model identifier to pass to the vLLM endpoint. |
| `LLM_API_KEY` | *(read from Hermes `.env`; **never hardcode**)* | API key for authenticating with the LLM server. |
| `LLM_TIMEOUT_SECONDS` | `15` | Timeout (seconds) for LLM HTTP requests. |
| `DB_PATH` | `/data/downtime.db` | Filesystem path to the SQLite database. |
| `SIMULATOR_ENABLED` | `true` | Set to `false` to disable the built‑in event simulator. |
| `SIMULATOR_INTERVAL_SECONDS` | `8` | Average interval (seconds) between simulated events. |
| `GITHUB_REPO` | `https://github.com/pl247/team-2` | GitHub repository URL (used for reference only). |
| `GHCR_IMAGE` | `ghcr.io/pl247/team-2` | Full image name for GitHub Container Registry. |

> **Note**: The `LLM_API_KEY` must be supplied via the environment; in development it is read from the Hermes agent’s `.env` file (never committed). For production, set it in the environment or in a `.env` file that is excluded by `.gitignore`.

## Prerequisites

- Docker Engine (version 20.10+)
- Docker Compose (v2)
- Access to a running vLLM server hosting the NVIDIA Nemotron model at the `LLM_BASE_URL` above.
- (Optional) A GitHub personal access token with `write:packages` scope for publishing the image (used by the GitHub Actions workflow).

## Quick Start (Ubuntu)

1. **Clone the repository** (if not already done):
   ```bash
   git clone https://github.com/pl247/team-2.git
   cd machine-downtime-log
   ```

2. **Create a `.env` file** (optional, for overriding defaults):
   ```bash
   cp .env.example .env   # if you have an example
   # Edit .env to set any non‑default values, especially LLM_API_KEY.
   ```
   The `.env` file is ignored by Git (see `.gitignore`).

3. **Build and start the container**:
   ```bash
   docker compose up --build -d
   ```
   The command will:
   - Check that `APP_PORT` (default 8742) is free.
   - Build the Docker image (if not already present).
   - Start the container, mounting `./data` for persistent SQLite storage.
   - Print logs to stdout; you can view them with `docker compose logs -f`.

4. **Open the dashboard**:
   Navigate to `http://localhost:8742` (or the port you set) in a web browser.

5. **Verify operation**:
   - You should see the "On‑Prem Secure" indicator.
   - The LLM indicator will show "LLM: Reachable" if the vLLM server is up and the key is valid.
   - Events will appear in the list, total downtime will update, and the worst machine will be highlighted.
   - Latency (ms) will be shown for each event as it arrives.

6. **Stopping the app**:
   ```bash
   docker compose down
   ```

## Publishing to GHCR (GitHub Container Registry)

The repository includes a GitHub Actions workflow (`.github/workflows/docker-publish.yml`) that automatically builds and pushes the Docker image to `GHCR_IMAGE` on pushes to the `main` branch.

To trigger a manual build and push:
1. Ensure you have a `GHCR_TOKEN` secret set in the repository Settings → Secrets → Actions (a personal access token with `write:packages` and `delete:packages` scopes, or use the default `GITHUB_TOKEN` with appropriate permissions).
2. Push a commit to `main` or manually run the workflow from the Actions tab.

## Project Structure

```
machine-downtime-log/
├── main.py               # FastAPI application entrypoint
├── requirements.txt      # Pinned Python dependencies
├── Dockerfile            # Multi‑stage (single‑stage) Docker image definition
├── docker-compose.yml    # Compose file for local development
├── .gitignore            # Excludes .env, /data, Python caches, etc.
├── README.md             # This file
└── .github/
    └── workflows/
        └── docker-publish.yml   # CI/CD: build and push Docker image to GHCR
```

## Design Decisions & On‑Prem Benefits

- **Zero Cloud Round‑Trip**: All processing (event ingestion, LLM inference, storage) happens locally. The UI latency indicator proves sub‑second response times.
- **Data Sovereignty**: Machine data never leaves the factory floor; the only external dependency is the locally hosted LLM server (which you control).
- **Fault Tolerance**: The LLM client never crashes the stream; on any error it falls back to `Unclassified`/`Medium` and continues.
- **Simplicity**: A single‑page UI with no build step reduces complexity and eliminates Node.js/Webpack tooling.
- **Operational Simplicity**: One container, one volume, one port. Easy to deploy on existing hardware or edge devices.

## Troubleshooting

- **Port already in use**: Change `APP_PORT` to a free port (e.g., `APP_PORT=8743 docker compose up`).
- **LLM unreachable**: Verify `LLM_BASE_URL` and `LLM_API_KEY` are correct; ensure the vLLM server is running and accessible from the container.
- **No events appearing**: Confirm `SIMULATOR_ENABLED=true` (or connect a real event stream). Check container logs for simulator output.
- **Database not persisting**: Ensure the `./data` directory exists and is writable; the compose volume mounts `./data` to `/data` inside the container.

## License

This project is proprietary—provided as part of the Hermes agent demonstration.

--- 

*Built with ❤️ for secure, on‑prem manufacturing intelligence.*