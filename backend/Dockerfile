FROM python:3.12-slim

# geno_one.py 가 https://one.genoray.com(Sectigo 발급) 호출 시 슬림 이미지의
# 오래된 루트/중간 인증서 번들로 "unable to get local issuer certificate" 발생 → 최신화.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir --upgrade certifi

# one.genoray.com 이 중간 인증서(Sectigo Public Server Authentication CA DV R36)를
# 핸드셰이크에서 보내지 않는 서버측 설정 오류 — 브라우저/Windows는 캐시된 인증서로
# 넘어가지만 컨테이너는 처음이라 실패함. 루트는 certifi에 이미 있으므로 중간 인증서만
# 번들에 추가.
COPY extra_ca ./extra_ca
RUN cat ./extra_ca/*.pem >> "$(python -c 'import certifi; print(certifi.where())')"

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
