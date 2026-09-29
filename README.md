# Edit game

> Tools to edit and publish jugger game videos: from the rushes of a tournament to a cut, rendered and published on
> YouTube with its thumbnail and description.

## What it does

- **Tournaments and games**: a tournament points at a directory of rushes; its games are generated from those files or
  created by hand, each with its two teams, number and win condition.
- **Cut editing**: in the game editor, a video player and a timeline let you mark every point (in/out), who scored
  it, side switches, set ends and warnings. The running score is derived from them.
- **Automatic cut proposal**: a model trained on past cuts (`game_autoedit`) listens to the audio of a game and proposes
  its points, with the side that won them. Its thresholds can be tuned from the editor without retraining.
- **Rendering**: a render queue runs ffmpeg jobs one at a time: proxies, archives, and cut renders with a scoreboard
  overlay and chapters, in several presets (`low`, `medium`, `high`, their AV1 variants, and `youtube`). NVENC is used
  when available, x264 otherwise.
- **Thumbnails and YouTube**: for every game with a `youtube` render, a thumbnail is built from a frame of the video
  and the two team logos, with a generated title and description (chapters included). Both are then uploaded to the
  YouTube video they are linked to.

## Architecture

| Part                        | Role                                                                           |
|-----------------------------|--------------------------------------------------------------------------------|
| `edit_game/`                | Django project settings and root URLs.                                         |
| `core/`                     | Models (tournaments, games, cuts, videos, render queue, YouTube), worker loop. |
| `api/`                      | Django REST Framework API (HAL links), served under `/api/`.                   |
| `jugger_video_manipulation/`| ffmpeg helpers, scoreboard overlay, thumbnail builder, cut parsing.           |
| `game_autoedit/`            | ML cut proposal: dataset, training, evaluation, Streamlit dashboard. See its [README](game_autoedit/README.md). |
| `frontend/`                 | Angular 20 + Angular Material app (light and dark theme).                      |

Paths are set in `edit_game/settings.py`:

- `TOURNAMENTS_BASE_DIR` (`/mnt/video/juggerData/tournois`): where tournament rushes live.
- `TOURNAMENTS_ARCHIVE_DIR` (`/mnt/jugger/tournois`): archive storage.
- `AUTOEDIT_RUN` / `AUTOEDIT_CACHE`: which trained run proposes cuts, and where the auto-edit cache is.

The database is SQLite (`db.sqlite3`).

## Requirements

- [uv](https://docs.astral.sh/uv/) to manage Python (3.12), the virtual environment and dependencies.
- Node.js and npm for the frontend.
- `ffmpeg` and `ffprobe`. An NVIDIA GPU with NVENC speeds up the `low`, `medium` and `high` presets.
- `nginx`, to serve the videos to the browser.
- Optionally [direnv](https://github.com/direnv/direnv) to load environment variables. The Makefile uses it when it is
  installed.

## Installation

### Python

```bash
uv sync
```

`uv run <command>` also installs what is missing before running it.

### Environment variables

```bash
cp .envrc.dist .envrc
direnv allow .envrc
```

Fill in:

- `DJANGO_SECRET_KEY`: any random string.
- `CLIENT_SECRET_FILE`: path to the Google OAuth client secret of the YouTube API.
- `CHANNEL_ID`: the YouTube channel to work on.

On the first YouTube call, a browser window asks for authorization; the token is then cached in
`token_youtube_v3.pickle` at the project root.

### Database

```bash
uv run python manage.py migrate
```

### Frontend

```bash
cd frontend
npm install
```

### Video server (nginx)

The video player in the browser reads the rushes and renders over HTTP, from a local nginx serving
`TOURNAMENTS_BASE_DIR` on http://localhost:8081/tournois (the URL `Tournament.tournament_media_url` builds). Its
configuration is specific to each machine and not versioned; create it from the template:

```bash
mkdir -p nginx/.nginx && cp nginx.conf.dist nginx/.nginx/nginx.conf
```

then set, in `nginx/.nginx/nginx.conf`:

- the `alias` of `location /tournois` to your `TOURNAMENTS_BASE_DIR`;
- the `include` to the `mime.types` of your nginx installation.

`make nginx-start`, `nginx-stop`, `nginx-reload` and `nginx-status` run it with `nginx/` as prefix, so its logs and pid
file stay in there. Tournaments stored in `TOURNAMENTS_ARCHIVE_DIR` are expected on another server,
http://192.168.1.2:8001/tournois.

## Running

Four processes, each in its own terminal:

```bash
make start-server                    # Django API on http://localhost:8000
uv run python manage.py qcluster     # render queue worker
make nginx-start                     # videos on http://localhost:8081/tournois
cd frontend && npm start             # app on http://localhost:4200
```

The frontend talks to the API at `http://localhost:8000/api/`. Stop nginx with `make nginx-stop`.

Editing a Python file reloads `runserver` and the worker: a render that was running is then left `RUNNING` and must be
put back to `WAITING`.

### Management commands

| Command                              | Purpose                                                     |
|--------------------------------------|-------------------------------------------------------------|
| `check_video_files`                  | Check every video file on disk and repair what it can.      |
| `delete_orphan_videos`               | Delete videos no game or cut points at.                     |
| `enque_archives`                     | Enqueue archive renders for games.                          |
| `rerender_oversized_archives`        | Re-queue archives left above 1080p (`--apply` to enqueue).  |
| `remove_tmp`                         | Remove temporary images.                                    |

Run them with `uv run python manage.py <command>`.

### Auto-edit

The pipeline and its commands are described in [game_autoedit/README.md](game_autoedit/README.md). The Makefile has
shortcuts (`make autoedit-inspect`, `make autoedit-cache`, …), and `make autoedit-dashboard` starts the Streamlit
dashboard on http://localhost:8501.

## Testing

```bash
make test
```

runs pytest (with pytest-django and model-bakery) over `tests/`, with coverage of `core`, `api`,
`jugger_video_manipulation` and `game_autoedit`.

Frontend unit tests:

```bash
cd frontend && npx ng test
```

## Formatting and static analysis

Python sources are `api`, `core`, `game_autoedit` and `jugger_video_manipulation`.

| Command            | What it runs                         |
|--------------------|--------------------------------------|
| `make format-check`| `ruff format --check`                |
| `make format-fix`  | `ruff format`                        |
| `make lint-check`  | `ruff check`                         |
| `make lint-fix`    | `ruff check --fix`                   |
| `make type-check`  | `mypy api core game_autoedit`        |

Frontend: `npm run format` (Prettier) in `frontend/`.
