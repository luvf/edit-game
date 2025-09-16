########################################################################################################################
# Project installation
########################################################################################################################

install:
	pyenv virtualenv --force 3.12.3 edit-game
	pyenv local edit-game
install-angular:
	npm install -g @angular/cli

########################################################################################################################
# Quality checksma
########################################################################################################################


test:
	uv run pytest tests --cov src --cov-report term --cov-report=html --cov-report xml --junit-xml=tests-results.xml

format-check:
	uv run ruff format --check edit_game  jugger_video_manipulation miniatures api

format-fix:
	uv run ruff format edit_game  jugger_video_manipulation miniatures api game_edit

lint-check:
	uv run ruff check edit_game  jugger_video_manipulation miniatures api game_edit

lint-fix:
	uv run ruff check edit_game  jugger_video_manipulation miniatures api game_edit --fix

type-check:
	uv run mypy edit_game miniatures api game_edit



########################################################################################################################
# Deployment
########################################################################################################################

start-server:
	uv run python manage.py runserver