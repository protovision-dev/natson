FROM natson-scraper:latest

# fastapi/uvicorn aren't in the scraper image; the scraper itself is CLI-only.
RUN pip install --no-cache-dir 'fastapi==0.115.5' 'uvicorn[standard]==0.32.1'

# Mounted at runtime as /app/jobs_api, but copy here for production builds
# in case the volume mount is removed in non-dev environments.
COPY server.py /app/jobs_api/server.py
COPY __init__.py /app/jobs_api/__init__.py

ENV PYTHONPATH=/app

EXPOSE 8770

CMD ["uvicorn", "jobs_api.server:app", "--host", "0.0.0.0", "--port", "8770"]
