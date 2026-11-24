FROM python:3.12-slim
WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Japanese font embedded in the assembly guide page of mesh PDFs.
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-ipaexfont-gothic \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd --system --uid 10001 --no-create-home app \
 && mkdir -p /data && chown 10001:10001 /data
COPY app ./app
USER app
EXPOSE 8086
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python","-c","import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8086/api/health',timeout=3).status==200 else 1)"]
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8086"]
