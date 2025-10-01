FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r <(python - <<'PY'
import tomllib,sys;print("
".join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))
PY
    )
COPY server.py /app/server.py
EXPOSE 3000
ENV MCP_TRANSPORT=http HOST=0.0.0.0 PORT=3000
CMD ["python", "-u", "server.py"]

