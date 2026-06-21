FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proxy.py .

EXPOSE 8001
ENV PROXY_PORT=8001

CMD ["python", "proxy.py"]
