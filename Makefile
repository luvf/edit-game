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
	uv run ruff format --check jugger_video_manipulation api core

format-fix:
	uv run ruff format jugger_video_manipulation api core

lint-check:
	uv run ruff check jugger_video_manipulation api core

lint-fix:
	uv run ruff check jugger_video_manipulation api core --fix

type-check:
	uv run mypy api core



########################################################################################################################
# Deployment
########################################################################################################################

start-server:
	uv run python manage.py runserver
