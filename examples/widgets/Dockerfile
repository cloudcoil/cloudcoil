FROM python:3.14-slim
WORKDIR /app
COPY pyproject.toml README.md /app/
COPY cloudcoil /app/cloudcoil
COPY .build/widgets-models /models
RUN pip install --no-cache-dir '.[operator]' /models && rm -rf /models
COPY examples/widget_operator.py /app/widget_operator.py
ENTRYPOINT ["python", "/app/widget_operator.py"]
