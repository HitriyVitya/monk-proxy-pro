FROM python:3.11-slim

WORKDIR /app

# Ставим зависимости системы
RUN apt-get update && apt-get install -y curl wget unzip

# Скачиваем sing-box
RUN wget https://github.com/SagerNet/sing-box/releases/download/v1.8.5/sing-box-1.8.5-linux-amd64.tar.gz \
    && tar -xvf sing-box-1.8.5-linux-amd64.tar.gz \
    && cp sing-box-1.8.5-linux-amd64/sing-box . \
    && chmod +x sing-box

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "main.py"]
