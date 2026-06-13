FROM python:3.11-slim

WORKDIR /app

# (build context is project root)
COPY frontend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY frontend/src/ ./src/

EXPOSE 8004

CMD ["uvicorn", "src.frontend:app", "--host", "0.0.0.0", "--port", "8004"]
