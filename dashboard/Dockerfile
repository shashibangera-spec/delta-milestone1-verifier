FROM python:3.12-slim
WORKDIR /app
COPY dashboard/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p ./amt_engine
COPY amt_engine/__init__.py ./amt_engine/__init__.py
COPY amt_engine/daily.py ./amt_engine/daily.py
COPY amt_engine/developing.py ./amt_engine/developing.py
COPY dashboard/test_developing_profile.py ./test_developing_profile.py
COPY dashboard/test_tpo.py ./test_tpo.py
COPY dashboard/oi_attribution.py ./oi_attribution.py
COPY dashboard/multi_day_research.py ./multi_day_research.py
COPY dashboard/test_oi_attribution.py ./test_oi_attribution.py
COPY dashboard/test_multi_day_research.py ./test_multi_day_research.py
COPY dashboard/test_observer_v1.py ./test_observer_v1.py
RUN python -m unittest discover -s . -p 'test_*.py' -v
COPY dashboard/observer_v1.py ./observer_v1.py
COPY dashboard/observer_v1_model.py ./observer_v1_model.py
COPY dashboard/app.py ./app.py
COPY dashboard/session_selection.py ./session_selection.py
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT} --server.headless true"]
