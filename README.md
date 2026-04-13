# Thu Vien Sach Noi AI

MVP dung Flask, templates va kho du lieu JSON de quan ly sach do admin them vao bang link Google Drive.

## Tinh nang hien tai

- Trang chu hien danh sach sach.
- Trang chi tiet sach co nut mo Google Drive, tai tep va khung preview.
- Trang admin cho phep them sach moi bang link Google Drive.
- Du lieu duoc luu trong `data/books.json`.
- Tao audio MP3 bang `gTTS` trong background khi user bam `Tao Audio`.
- Chia audio thanh nhieu phan nho de user nghe som va theo doi tien do theo phan tram.
- Ho tro doc noi dung tu Google Docs, PDF, DOCX va TXT neu file co quyen xem cong khai.
- Co trang `/camera` de mo camera tren trinh duyet va gui anh len Gemini nhan dien vat the, doc chu trong anh.
- Mac dinh khong tu tao audio ngay khi them sach; user chu dong bam `Tao Audio` khi can.
- Co dang nhap/dang ky tuy chon cho user va khoa trang admin bang tai khoan admin.
- User co the xem tien do tao audio va chinh toc do phat 1x, 1.5x, 2x, 3x.

## Chay du an

1. Tao hoac chinh file `.env` theo mau trong `.env.example`.
2. Chay lenh:

```bash
pip install -r requirements.txt
python app.py
```

Sau do mo `http://127.0.0.1:5000`.

Neu muon dung camera AI, them `GEMINI_API_KEY` vao `.env`, sau do truy cap `http://127.0.0.1:5000/camera`.

Trang admin nam tai `http://127.0.0.1:5000/admin/books`. Neu chua cau hinh, tai khoan admin mac dinh la `admin` / `admin123`; nen doi `ADMIN_USERNAME` va `ADMIN_PASSWORD` trong `.env` truoc khi deploy.

## Deploy len Render

Du an da co san `render.yaml`, `Procfile` va `gunicorn.conf.py`.

### Cach 1: Dung Blueprint

1. Push code len GitHub.
2. Tren Render, chon `New` -> `Blueprint`.
3. Chon repo co file `render.yaml`.
4. Render se tao service, disk va env vars theo cau hinh.

### Cach 2: Tao Web Service thu cong

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app -c gunicorn.conf.py`
- Health check path: `/healthz`
- Env vars quan trong:
  - `SECRET_KEY`: tao chuoi bi mat rieng.
  - `FLASK_DEBUG=0`
  - `DATA_FILE=/var/data/books.json`
  - `AUDIO_DIR=/var/data/audio`
  - `AUDIO_PUBLIC_URL=/media/audio`
  - `RECOVER_AUDIO_JOBS_ON_STARTUP=1`
  - `WEB_CONCURRENCY=1`
  - `GUNICORN_THREADS=4`
  - `GUNICORN_TIMEOUT=300`
  - `GEMINI_API_KEY`: can them neu muon dung trang camera AI.
  - `GEMINI_MODEL=gemini-2.5-flash`

Can gan Render Disk vao mount path `/var/data`, vi Render filesystem mac dinh co the mat du lieu khi redeploy/restart. `books.json` va audio MP3 nen nam trong disk nay.

## Huong mo rong

- Doi `JSON` sang `SQLite/PostgreSQL`.
- Them module TTS cho sach dai.
- Them OCR local cho PDF scan.
- Chi dung Gemini cho camera, vision va fallback OCR.
- Tach job audio sang queue that su nhu Redis/RQ/Celery neu luu luong lon hon.
