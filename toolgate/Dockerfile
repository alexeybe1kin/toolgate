FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY toolgate/requirements.txt ./toolgate/requirements.txt
RUN pip install --no-cache-dir -r toolgate/requirements.txt
COPY toolgate ./toolgate
EXPOSE 8010
CMD ["uvicorn", "toolgate.api.server:app", "--host", "0.0.0.0", "--port", "8010"]
