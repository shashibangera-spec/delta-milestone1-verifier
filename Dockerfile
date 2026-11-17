FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY oi_metrics.py .
COPY milestone1_delta_verify.py .
COPY tests ./tests
RUN python -m unittest discover -s tests -v
ENV PYTHONUNBUFFERED=1 OBSERVATION_SECONDS=600
CMD ["python", "milestone1_delta_verify.py"]
