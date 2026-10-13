FROM debian:bookworm-slim

# The man directory is missing in slim images and the JDK's post-install step needs it.
RUN mkdir -p /usr/share/man/man1 \
    && apt-get update \
    && apt-get install -y --no-install-recommends python3 openjdk-17-jdk-headless nodejs g++ \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY runner.py /opt/runner/runner.py

USER nobody
WORKDIR /tmp
CMD ["python3", "/opt/runner/runner.py"]
