
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