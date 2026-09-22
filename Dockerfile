# PurffleShorts — run the autopilot in a container.
#   docker build -t purffle-shorts .
#   docker run --rm -it --env-file .env -v "$PWD:/work" purffle-shorts run
# Authorize YouTube once on your computer (python -m purffle_shorts auth) so token.json exists in /work.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core espeak-ng \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY purffle_shorts ./purffle_shorts
RUN pip install --no-cache-dir .

WORKDIR /work
ENTRYPOINT ["purffle-shorts"]
CMD ["run"]
