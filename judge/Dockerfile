# Ảnh chấm bài: g++ (C++17/20), Python 3.12 (+numpy), OpenJDK 17, Node.js.
# docker build -t codechalk-judge:latest judge/
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends g++ default-jdk-headless nodejs \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir numpy

COPY runner.py /judge/runner.py
WORKDIR /box
USER 65534:65534
CMD ["python3", "/judge/runner.py", "/box"]
