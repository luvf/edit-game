# Edit game

> Set of tools to help you edit your jugger game, starting with miniature generator.

## Project Description

the project is sructured as follow:
A backend server with django rest framework and a frontend with angular.
the server matches videos in local directory with video on a spcific youtube chanel.
and provides a way to edit the miniature and metadata of the video.
FUTURE : be able te cut and generate the hole video from rushs.

## Project requirements

### `uv`

- Install [uv](https://docs.astral.sh/uv/) to manage Python versions, virtual environments and dependencies:
    ```bash
    curl -LsSf https://astral.sh/uv/0.4.20/install.sh | sh
    ```

### `direnv`

- To easily handle project environment variables, we recommend
  installing [Direnv](https://github.com/direnv/direnv/tree/master)
  shell extension. For instance, on MacOS:
    ```bash
    brew install direnv
    ```
- Add these lines to your `~/.bashrc` or `~/.zshrc`:
    ```bash
    # Set up direnv
    eval "$(direnv hook zsh)"
    ```

## Installation

### Python virtual environment and dependencies

- You can simply run Python shell through `uv`:
    ```bash
    uv run python
    ```
  Thanks to uv's magic, this will automatically install `Python` version defined in `pyproject.toml`, create a virtual
  environment at `.venv`, install dependencies to the `venv` and run Python from the `venv`.

  `uv run ...` command indeed allows launching Python shell, Python scripts or Python packages entrypoints within the
  project `venv` (after installing missing Python version or Python packages if needed).

### Install git hooks (running before commit and push commands)

```bash
uv run pre-commit install
```

### Set-up project environment variables and venv auto-activating using Direnv

- Create an `.envrc` file:
    ```bash
    cp .envrc.dist .envrc
    ```
  This file will be sourced each time you enter into your project directory within a terminal.
  CHANNEL_ID
  CLIENT_SECRET_FILE
  DJANGO_SECRET_KEY
- Fill missing values in the `.envrc` file:
    - `CHANNEL_ID`: id of the youtube channel you want to work on.
    - `CLIENT_SECRET_FILE`: path to the file containing the client secret.
    - `DJANGO_SECRET_KEY`: a random string to be used as Django secret key.

- To apply your change, run:
    ```bash
    direnv allow .envrc
    ```
  You will need to run this command each time you edit the `.envrc` file.

- The line `source .venv/bin/activate` in `.envrc` file will automatically activate the project `venv` each time you
  enter the project directory, so that you can simply run Python scripts or packages without using `uv run` command.
  Please note that `uv run` is a bit safer, compared to directly calling Python or packages commands, because it
  automatically syncs dependencies with `uv.lock` if they have changed.

## Testing

To run unit tests, run `pytest` with:

```bash
pytest tests --cov src
```

or

```bash
make test
```

## Formatting and static analysis

### Code formatting with `ruff`

To check code formatting, run `ruff format` with:

```bash
ruff format --check .
```

or

```bash
make format-check
```

You can also [integrate it to your IDE](https://docs.astral.sh/ruff/integrations/) to reformat
your code each time you save a file.

### Static analysis with `ruff`

To run static analysis, run `ruff` with:

```bash
ruff check src tests
```

or

```bash
make lint-check
```

To run static analysis and to apply auto-fixes, run `ruff` with:

```bash
make lint-fix
```

### Type checking with `mypy`

To type check your code, run `mypy` with:

```bash
mypy src --explicit-package-bases --namespace-packages
```

or

```bash
make type-check
```

## Troubleshooting

No troubleshooting for now 😎.
