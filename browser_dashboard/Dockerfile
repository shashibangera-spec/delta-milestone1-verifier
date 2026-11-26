FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY browser_dashboard/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY browser_dashboard/main.py ./main.py
COPY amt_engine/__init__.py ./amt_engine/__init__.py
COPY amt_engine/playbook_v13.py ./amt_engine/playbook_v13.py
EXPOSE 8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
