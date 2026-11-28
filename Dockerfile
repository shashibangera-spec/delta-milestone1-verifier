FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY oi_metrics.py .
COPY milestone1_delta_verify.py .
COPY continuous_collector.py .
COPY tests ./tests
RUN python -m unittest tests/test_continuous_collector.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "continuous_collector.py"]
