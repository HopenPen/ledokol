FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
WORKDIR /mocks
RUN uv pip install --system fastapi "uvicorn[standard]" pandas
COPY *.py ./
