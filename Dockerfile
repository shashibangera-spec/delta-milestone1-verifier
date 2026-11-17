FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY milestone1_delta_verify.py .
ENV PYTHONUNBUFFERED=1 OBSERVATION_SECONDS=3900
CMD ["python", "milestone1_delta_verify.py"]
