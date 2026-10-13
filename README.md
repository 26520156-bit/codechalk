<p align="center"><img src="docs/cover.jpg" alt="CodeChalk" width="820"></p>

# CodeChalk

**Nền tảng luyện lập trình C++/Python có trợ giảng AI.** Viết code, chạy và chấm bài tự động ngay trên trình duyệt.

**Dùng thử:** https://actoflove.io.vn

## Tính năng chính

- **Challenge 929 bài**, chấm tự động theo bộ test (C++, Python, Java, JavaScript).
- **Trợ giảng AI**: gợi ý hướng giải, chỉ ra lỗi sai, sửa lỗi và đưa code đáp án đã được kiểm chứng bằng chính bộ test của bài.
- **Code War**: đấu code thời gian thực.
- **Lớp học, phòng thi** cho giảng viên; thời khoá biểu có nhắc lịch.
- **Bảng xếp hạng, XP, Bcoins** và shop đổi thưởng.
- Forum chat thời gian thực, kho tài liệu, thanh toán VietQR, trang quản trị HOST.

## Công nghệ

| Phần | Công nghệ |
|---|---|
| Máy chủ | Python, FastAPI, SQLAlchemy, WebSocket |
| Cơ sở dữ liệu | PostgreSQL 16 (SQLite khi chạy thử) |
| Máy chấm | Docker sandbox: không mạng, ổ chỉ đọc, giới hạn CPU/RAM |
| AI | Google Gemini, Anthropic, OpenAI hoặc Ollama |
| Giao diện | HTML, CSS, JavaScript (một trang `web/index.html`) |
| Triển khai | Docker Compose, Caddy (HTTPS tự động), VPS Ubuntu |

---

## Chạy nhanh trên Windows (5 phút, không cần Docker)

1. Cài **Python 3.13** (hoặc 3.12) từ python.org. Khi cài, tick **"Add python.exe to PATH"**. Có thể cài song song với bản mới hơn; `run_dev.bat` tự ưu tiên 3.13 → 3.12 → 3.11.
2. Mở thư mục này, nhấp đúp **`run_dev.bat`**. Lần đầu, script làm ba việc:
   - tạo `.venv` và cài thư viện (cần mạng);
   - hỏi email, **mật khẩu HOST**, số điện thoại và tài khoản nhận tiền VietQR (đã gợi ý sẵn, Enter để giữ), rồi tạo file `.env`;
   - mở trình duyệt tại http://localhost:8000.
3. Đăng nhập HOST bằng email và mật khẩu vừa nhập.
4. Muốn thiết lập lại: chạy `python scripts/setup_env.py --force`, hoặc sửa thẳng file `.env`.

Dữ liệu được lưu vào `data/codechalk.db` (SQLite) và `data/uploads/`.

**Chấm bài C++ khi chạy local trên Windows** cần `g++`:

1. Cài MSYS2.
2. Chạy `pacman -S mingw-w64-ucrt-x86_64-gcc`.
3. Thêm `C:\msys64\ucrt64\bin` vào PATH.

Python được chấm bằng chính Python của máy chủ. Java cần JDK, JavaScript cần Node.js.

> Chế độ `JUDGE_MODE=local` chạy code của người nộp ngay trên máy bạn, chỉ dùng khi thử một mình. Khi mở cho người khác dùng, hãy chạy bằng Docker như bên dưới.

## Mở cho bạn bè dùng thật: chạy bằng Docker

Bản Docker gồm 3 phần:

- `db`: PostgreSQL 16, dữ liệu nằm trong volume nên không mất khi tắt máy.
- `judge-image`: ảnh chấm bài có g++, Python, Java, Node.
- `app`: máy chủ ở cổng 8000. Mỗi bài nộp chạy trong một container riêng:
  - không có mạng, ổ chỉ đọc, người dùng không đặc quyền;
  - giới hạn CPU, RAM và số tiến trình;
  - chỉ thấy thư mục bài của chính mình.

Khác với `run_dev.bat`, code của người nộp không đụng được vào máy bạn.

### Bước 1: Cài Docker Desktop (một lần)

1. Tải tại docker.com/products/docker-desktop rồi cài, giữ lựa chọn **Use WSL 2**. Cài xong khởi động lại máy.
2. Mở Docker Desktop, đợi góc dưới bên trái hiện **Engine running**.
3. Nên bật **Settings → General → Start Docker Desktop when you sign in**, để máy bật lên là CodeChalk tự chạy.

### Bước 2: Khởi động

1. Đóng cửa sổ `run_dev.bat` nếu đang mở, vì hai bản cùng dùng cổng 8000.
2. Nhấp đúp **`docker_start.bat`**. Lần đầu mất 3–10 phút để tải và dựng ảnh.
3. Khi chạy xong, script in ra các địa chỉ:
   - `http://localhost:8000` cho máy này;
   - `http://192.168.x.x:8000` cho bạn bè **cùng Wi-Fi**. Nếu Windows hỏi về tường lửa, chọn **Allow**.

Dữ liệu từ bản `run_dev.bat` (tài khoản, bài nộp, cấu hình AI…) **không tự chuyển sang**. Muốn giữ, nhấp đúp **`docker_import_sqlite.bat`** một lần.

### Bước 3: Link cho bạn bè ở xa

Nhấp đúp **`docker_public.bat`**. Script mở một đường hầm Cloudflare miễn phí và in ra link dạng `https://….trycloudflare.com` (đã chép sẵn vào clipboard) để gửi bạn bè.

- Link chỉ dùng được khi máy bạn đang bật và Docker Desktop đang chạy.
- Link đổi mỗi lần chạy lại `docker_public.bat` hoặc khởi động lại máy.
- Muốn **link cố định** với tên miền riêng:
  1. Tạo Tunnel trong Cloudflare Zero Trust, trỏ hostname tới `http://app:8000`.
  2. Dán token vào `.env` dạng `CLOUDFLARE_TUNNEL_TOKEN=…`.
  3. Chạy `docker compose --profile domain up -d`.

### Trước khi gửi link, kiểm tra 4 việc

1. Đã đổi mật khẩu HOST: **Tài khoản → Đổi mật khẩu**.
2. Đã bật AI: **Quản trị → AI**.
3. Lượt AI mỗi ngày đủ dùng: Tự học 20 lượt/người, gói Ôn thi/Lớp học 300 lượt. Lượt này giúp không ai dùng hết hạn mức khoá AI của bạn.
4. Đăng nhập sai quá 10 lần trong 15 phút sẽ bị chặn tạm thời (chống dò mật khẩu).

### Lệnh hay dùng

| Việc | Lệnh |
|---|---|
| Dừng (giữ dữ liệu) | `docker_stop.bat` |
| Cập nhật sau khi sửa code | chạy lại `docker_start.bat` (tự build lại) |
| Xem nhật ký máy chủ | `docker compose logs -f app` |
| Tắt link công khai | `docker compose stop tunnel` |
| Sao lưu CSDL | `docker compose exec db pg_dump -U codechalk codechalk > backup.sql` |
| Xoá sạch dữ liệu (cẩn thận) | `docker compose down -v` |

Linux/macOS dùng thẳng các lệnh `docker compose up -d --build` và `docker compose --profile public up -d`. Link công khai xem bằng `docker compose logs tunnel`.

## Đưa lên Internet: một địa chỉ cố định, chạy 24/7 (VPS + tên miền)

Web chạy trên một máy chủ thuê (VPS) với tên miền riêng, ví dụ `https://codechalk.io.vn`, giống mọi website khác: không cần bật máy tính của bạn.

Trên VPS chạy đúng bản Docker ở trên, thêm **Caddy**:

- Caddy tự xin và gia hạn chứng chỉ HTTPS miễn phí (Let's Encrypt).
- `www.` tự chuyển về tên miền chính.
- Cổng 8000 của máy chủ không mở ra ngoài.

### 1. Mua tên miền `.io.vn`

- Mua tại một nhà đăng ký tên miền `.vn` (ví dụ Mắt Bão, PA Vietnam, Nhân Hòa, iNET, Tenten…).
- Mức phí nhà nước là 10.000đ đăng ký và 20.000đ/năm duy trì. Nhà đăng ký thường cộng thêm phí dịch vụ.
- Tên miền `.vn` cần khai báo CCCD để định danh.

### 2. Thuê VPS

- Chọn gói **Ubuntu 24.04**, có **IPv4 riêng** và **quyền root**.
- Tối thiểu **2 GB RAM, 25 GB SSD**. Máy 1 GB vẫn chạy được vì script tự tạo swap, nhưng chậm khi chấm nhiều bài cùng lúc.
- Nhà cung cấp sẽ gửi **IP** và **mật khẩu root**.
- Nếu dùng Oracle Cloud (gói Always Free): mở thêm cổng 80 và 443 trong **Security List** của VCN.

### 3. Trỏ tên miền về VPS

Trong trang quản lý tên miền (DNS), tạo 2 bản ghi:

| Loại | Tên | Giá trị |
|---|---|---|
| A | `@` | IP của VPS |
| CNAME | `www` | `codechalk.io.vn` |

DNS thường cập nhật sau vài phút đến vài giờ.

### 4. Cài đặt: nhấp đúp `deploy_vps.bat`

Script hỏi IP VPS và tên đăng nhập (`root`), rồi tự làm phần còn lại:

1. Đóng gói mã nguồn. Không kèm `.env`, `.venv` và dữ liệu thử.
2. Hỏi có chuyển **dữ liệu đang chạy trên máy này** (tài khoản, bài nộp, cấu hình AI, tệp tải lên) lên VPS không.
3. Tải lên VPS. Lần đầu kết nối, gõ `yes` rồi nhập mật khẩu.
4. Chạy `deploy/setup_vps.sh` trên VPS. Script này:
   - cập nhật hệ thống và bật tường lửa (chỉ mở cổng 22, 80, 443);
   - bật fail2ban chống dò mật khẩu SSH, tạo swap, cài Docker;
   - tạo `.env` (hỏi mật khẩu HOST) và hỏi tên miền;
   - kiểm tra DNS đã trỏ đúng chưa rồi khởi động mọi thứ;
   - đặt lịch **sao lưu tự động 3:30 sáng mỗi ngày**, giữ 14 ngày.

Xong là web chạy tại `https://tên-miền-của-bạn`. Từ đây chỉ dùng **một địa chỉ này**. Bản Docker trên máy tính có thể tắt bằng `docker_stop.bat`.

### Sau khi lên mạng

| Việc | Cách làm |
|---|---|
| Cập nhật code mới | nhấp đúp `deploy_update.bat` (máy chủ tự sao lưu trước khi cập nhật) |
| Xem nhật ký | SSH vào VPS: `cd /opt/codechalk && docker compose logs -f app` |
| Sao lưu ngay | trên VPS: `bash /opt/codechalk/deploy/backup.sh` |
| Tải bản sao lưu về máy | `scp root@IP:/opt/codechalk/backups/* .` |
| Khôi phục | trên VPS: `bash deploy/restore.sh backups/db_….sql.gz backups/uploads_….tgz` |

Bảo mật đã bật sẵn:

- Mỗi bài nộp chạy trong container riêng.
- Đăng nhập sai nhiều lần bị chặn tạm.
- Khoá AI, mật khẩu và `.env` chỉ nằm trên VPS (quyền 600).

Nên đổi mật khẩu root của VPS sau khi cài (`passwd`), hoặc chuyển sang đăng nhập bằng khoá SSH.

## Linux / macOS / WSL không dùng Docker

```bash
bash run_dev.sh
```

Trên Windows có cài WSL (Ubuntu): mở Ubuntu, chạy `sudo apt install python3-venv python3-pip g++`, rồi `cd /mnt/c/AI_Brain/CodeChalk/platform && bash run_dev.sh`. Mở http://localhost:8000 bằng trình duyệt Windows như bình thường. Cách này không bị Smart App Control chặn và chấm được C++ ngay.

## Cấu hình `.env`

| Nhóm | Biến | Ghi chú |
|---|---|---|
| HOST | `HOST_EMAIL`, `HOST_PASSWORD`, `HOST_PHONE`, `HOST_NAME` | Tài khoản chỉ được tạo một lần, khi chưa có. Sau đó đổi mật khẩu trong trang **Tài khoản → Đổi mật khẩu** (sửa `.env` không đổi được mật khẩu của tài khoản đã tạo). |
| VietQR | `BANK_BIN`, `BANK_NAME`, `BANK_ACCOUNT`, `BANK_HOLDER` | VietinBank = 970415. Mã QR đã có số tiền và nội dung `SUB_{USER_ID}_{TIER_ID}`. |
| Bảo mật | `JWT_SECRET` | Chuỗi ngẫu nhiên dài. **Không** chia sẻ. |
| CSDL | `DATABASE_URL` | Bỏ trống = SQLite. PostgreSQL: `postgresql+psycopg://user:pass@host:5432/codechalk`, và cài thêm `pip install -r requirements-postgres.txt` |
| AI | `AI_PROVIDER` = `gemini` / `anthropic` / `openai` / `ollama`, `AI_API_KEY`, `AI_MODEL`, `AI_BASE_URL` | Nên bật ngay trên giao diện: **Quản trị → AI** (ghi đè `.env`). Khoá nằm trên server, người học không thấy. |
| Email | `SMTP_HOST=smtp.gmail.com`, `SMTP_USER`, `SMTP_PASSWORD` | Gmail: bật xác minh 2 bước, tạo **App Password** 16 ký tự. |
| Bcoins | `CODEWAR_REWARDS`, `EXAM_REWARDS`, `CODEWAR_MIN_PLAYERS` | Mặc định Top 1→10 nhận 10→1 Bcoins; Code War cần ≥ 3 người có điểm. |

Kiểm tra cấu hình: mở http://localhost:8000/api/health. Kết quả cho biết máy chấm, AI, email và thanh toán đã sẵn sàng chưa.

## Lỗi thường gặp

| Thông báo | Nguyên nhân | Cách xử lý |
|---|---|---|
| `Failed to build 'pyyaml'`, `Cython does not appear to be installed` | Bản cũ của `requirements.txt` cần PyYAML, mà PyYAML chưa có bản dựng sẵn cho Python 3.15 nên pip phải tự biên dịch | Bản hiện tại đã bỏ PyYAML. Chạy lại `run_dev.bat`; script tự xoá `.venv` cài dở và cài lại |
| `An Application Control policy has blocked this file` | **Smart App Control** của Windows 11 chặn tệp thư viện (.pyd/.dll) chưa có "uy tín" | Ưu tiên dùng Python 3.13 (thư viện dựng sẵn phổ biến hơn). Nếu vẫn bị chặn: chạy trong WSL (mục "Linux / macOS / WSL" ở trên) hoặc Docker Desktop. Cách cuối cùng: Windows Security → App & browser control → Smart App Control → **Off** (lưu ý: trên nhiều bản Windows, đã tắt thì không bật lại được nếu không cài lại Windows) |
| `Khong tim thay Python` | Python chưa có trong PATH | Cài lại Python, tick "Add python.exe to PATH" |
| Trình duyệt báo không kết nối được | Máy chủ chưa khởi động xong hoặc đã dừng vì lỗi | Đợi vài giây rồi F5; xem dòng lỗi trong cửa sổ đen |
| `address already in use` / cổng 8000 bận | Một bản máy chủ khác đang chạy | Đóng cửa sổ đen cũ rồi chạy lại |

## Việc của HOST

- **Quản trị → Thanh toán**:
  1. Đối chiếu sao kê ngân hàng với nội dung `SUB_…` của đơn.
  2. Bấm **Duyệt**. Gói được kích hoạt ngay và người mua nhận thông báo.
- **Quản trị → Đổi thưởng**:
  1. Mở ảnh QR hoặc số tài khoản của người đổi.
  2. Chuyển tiền.
  3. Bấm **XÁC NHẬN ĐÃ CHUYỂN TIỀN**.
  - Nếu từ chối, Bcoins được hoàn tự động.
- **Quản trị → Tài khoản**: đổi TAG SINH VIÊN ↔ GIÁO VIÊN, sửa thông tin, khoá tài khoản, cấp gói thủ công.
- **Quản trị → Gói**: sửa giá và thời hạn.

## Bật AI (gợi ý, sửa lỗi, code đáp án, AI CHẤM)

1. Đăng nhập HOST, vào **Quản trị → AI** (hoặc bấm **Bật AI ngay** trong khung Trợ lý AI của một bài Challenge).
2. Chọn **Google Gemini**, dán khoá lấy miễn phí ở aistudio.google.com/apikey (bấm *Create API key*).
3. Bấm **Kiểm tra kết nối**, rồi **Lưu**. Không cần sửa `.env` hay khởi động lại máy chủ.

Không muốn dùng khoá: cài Ollama, chạy `ollama pull qwen2.5-coder:7b`, chọn **Ollama** rồi bấm **Tải danh sách model**.

## Challenge

`data/challenges.json` có 929 bài từ tài liệu "1000 bài code thiếu nhi". 178 bài đã có bộ test chấm tự động (chương 1–4 và Đệ quy); các bài còn lại do AI chấm.

Mỗi bài có khung **Trợ lý AI** ngay dưới trình soạn code:

| Nút | Làm gì | XP khi giải xong |
|---|---|---|
| Gợi ý hướng làm | Ý tưởng từng bước, chưa có code | Giữ nguyên |
| Gợi ý code | Khung code tiếp theo, phần lõi để `TODO` cho người học tự viết | Giữ nguyên |
| Vì sao code sai? | Chỉ dòng lỗi, nguyên nhân, cách sửa bằng lời | Giữ nguyên |
| Giải thích code | Giải thích code đang viết | Giữ nguyên |
| Sửa lỗi giúp tôi | Sửa tối thiểu trên code của người học, hiện các dòng đã sửa, nút đưa vào trình soạn | Còn 50% |
| Xem code đáp án | Ý tưởng, độ phức tạp, code hoàn chỉnh, giải thích từng bước | Không cộng |

Code do AI viết (sửa lỗi, đáp án) được **chạy thật trên bộ test của bài** trước khi hiện ra. Nếu sai, AI được xem kết quả chạy và sửa lại một lần. Đáp án đúng hết test được lưu lại: người sau xem không tốn lượt AI.

Để bổ sung test:

1. Sửa trường `tests` của bài trong `data/challenges.json`.
2. Chạy:

```bash
python scripts/load_challenges.py
```

## Kiểm thử

```bash
pip install -r requirements-dev.txt
pytest -q tests
```

## Cấu trúc thư mục

```
app/            máy chủ FastAPI (routers = API, services = nghiệp vụ, models = bảng CSDL)
deploy/         đưa lên VPS: setup_vps.sh, update.sh, backup.sh, restore.sh, Caddyfile (HTTPS)
judge/          runner.py chấm bài + Dockerfile ảnh chấm
web/index.html  giao diện (trang học + nền tảng)
data/           challenges.json, CSDL SQLite, tệp tải lên
docs/           ARCHITECTURE.md: phân tích, sơ đồ CSDL, API, luồng nghiệp vụ
scripts/        setup_env.py (tạo .env), load_challenges.py (nạp lại Challenge)
tests/          kiểm thử tự động
```

Chi tiết kiến trúc, quyền, luồng thanh toán, chấm điểm và chống gian lận Bcoins: xem `docs/ARCHITECTURE.md`.


## Tác giả

Nguyễn Huỳnh Gia Bảo, sinh viên Kỹ thuật Phần mềm, Trường ĐH Công nghệ Thông tin (UIT), ĐHQG-HCM.

## Giấy phép

Mã nguồn phát hành theo giấy phép MIT, xem tệp `LICENSE`. Đề bài trong `data/challenges.json` được biên soạn lại từ tài liệu "1000 bài code thiếu nhi"; bản quyền đề gốc thuộc về tác giả tài liệu.
