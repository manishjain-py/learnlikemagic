FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app/
ENV API_HOST=0.0.0.0 API_PORT=8000
EXPOSE 8000
# Copy and make entrypoint script executable
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
# Use bash to run the entrypoint script
CMD ["bash", "/app/entrypoint.sh"]