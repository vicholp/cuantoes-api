FROM python:3.13.6-alpine

RUN apk add --no-cache ffmpeg

WORKDIR /app

COPY requirements.txt .

RUN pip install wheel setuptools pip --upgrade
RUN pip install -r requirements.txt

COPY . .
