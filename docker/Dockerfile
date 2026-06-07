FROM python:3.14 as base

# Assumes:
# - `uv build` was invoked *outside*, and the wheel is already in `dist` directory.
# - requirements.txt was generated, e.g. with `uv export --format=requirements.txt --no-dev`
WORKDIR /dist

COPY /dist .
COPY /docker/requirements.txt .

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install -r /dist/requirements.txt
RUN pip install --no-deps `ls /dist/libksef*whl`

VOLUME ["/state"]

CMD ["ksef.notifier", "--tokens_file=/state/tokens", "--state_file=/state/state"]
