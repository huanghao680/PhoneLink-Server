FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
RUN mkdir -p /app/data
EXPOSE 8765 8766
CMD ["python3", "server.py", "--forward"]
