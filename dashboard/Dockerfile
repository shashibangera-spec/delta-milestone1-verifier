FROM python:3.12-slim
WORKDIR /app
COPY dashboard/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY dashboard/test_tpo.py ./test_tpo.py
COPY dashboard/oi_attribution.py ./oi_attribution.py
COPY dashboard/test_oi_attribution.py ./test_oi_attribution.py
RUN python -m unittest discover -s . -p 'test_*.py' -v
COPY dashboard/app.py ./app.py
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT} --server.headless true"]
