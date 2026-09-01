
NGINX_PREFIX := $(CURDIR)/nginx
NGINX_CONF := .nginx/nginx.conf
NGINX_PID := tmp/nginx/nginx.pid

.PHONY: nginx-start nginx-stop nginx-reload nginx-status runserver dev


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


SOURCES := jugger_video_manipulation api core game_autoedit

test:
	uv run pytest tests --cov core --cov api --cov jugger_video_manipulation --cov game_autoedit --cov-report term --cov-report=html --cov-report xml --junit-xml=tests-results.xml

format-check:
	uv run ruff format --check $(SOURCES)

format-fix:
	uv run ruff format $(SOURCES)

lint-check:
	uv run ruff check $(SOURCES)

lint-fix:
	uv run ruff check $(SOURCES) --fix

type-check:
	uv run mypy api core game_autoedit



########################################################################################################################
# Auto-edit (génération de cuts par ML)
########################################################################################################################

AUTOEDIT := uv run python -m game_autoedit

autoedit-inspect:
	$(AUTOEDIT) inspect

autoedit-cache:
	$(AUTOEDIT) build-cache

autoedit-cache-status:
	$(AUTOEDIT) cache-status

autoedit-splits:
	$(AUTOEDIT) splits

autoedit-embeddings:
	$(AUTOEDIT) build-embeddings

autoedit-dashboard:
	$(RUN) streamlit run game_autoedit/dashboard/app.py


########################################################################################################################
# Deployment
########################################################################################################################

# direnv charge .envrc (DJANGO_SECRET_KEY, CHANNEL_ID, ...). Les runners d'IDE
# (config Makefile PyCharm, etc.) ne passent pas par le shell, donc pas par le
# hook direnv : on l'appelle explicitement quand il est disponible.
DIRENV := $(shell command -v direnv 2>/dev/null)
ifdef DIRENV
RUN := direnv exec . uv run
else
RUN := uv run
endif

start-server:
	$(RUN) python manage.py runserver


nginx-start:
	@if [ -f "$(NGINX_PID)" ] && kill -0 "$$(cat $(NGINX_PID))" 2>/dev/null; then \
		echo "Nginx est déjà lancé avec le PID $$(cat $(NGINX_PID))"; \
	else \
		echo "Démarrage de Nginx sur http://localhost:8081"; \
		nginx -p "$(NGINX_PREFIX)" -c "$(NGINX_CONF)"; \
	fi

nginx-stop:
	@if [ -f "$(NGINX_PID)" ]; then \
		echo "Arrêt de Nginx avec le PID $$(cat $(NGINX_PID))"; \
		nginx -p "$(NGINX_PREFIX)" -c "$(NGINX_CONF)" -s quit || true; \
		rm -f "$(NGINX_PID)"; \
	else \
		echo "Aucun PID Nginx trouvé"; \
	fi

nginx-reload:
	@if [ -f "$(NGINX_PID)" ] && kill -0 "$$(cat $(NGINX_PID))" 2>/dev/null; then \
		echo "Reload de Nginx"; \
		nginx -p "$(NGINX_PREFIX)" -c "$(NGINX_CONF)" -s reload; \
	else \
		echo "Nginx n'est pas lancé"; \
	fi

nginx-status:
	@if [ -f "$(NGINX_PID)" ] && kill -0 "$$(cat $(NGINX_PID))" 2>/dev/null; then \
		echo "Nginx est lancé avec le PID $$(cat $(NGINX_PID))"; \
	else \
		echo "Nginx n'est pas lancé"; \
	fi


dev: nginx-start
	python manage.py runserver