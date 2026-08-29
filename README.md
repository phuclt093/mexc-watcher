# Launchpool Watcher → Telegram

Bot tự động theo dõi **Launchpool / Airdrop+ / Kickstarter** của MEXC và **GemPool** của
KuCoin, có bài mới là bắn tin về Telegram. Chạy miễn phí trên GitHub Actions, không cần bật máy.

---

## 1. Tạo bot Telegram (2 phút)

1. Mở Telegram, chat với **@BotFather** → gõ `/newbot`
2. Đặt tên + username (phải kết thúc bằng `bot`, ví dụ `mexc_launchpool_phuc_bot`)
3. BotFather trả về **token** dạng `1234567890:AAH...` → lưu lại

**Lấy `chat_id`:**

1. Nhắn `/start` (hoặc chữ gì cũng được) cho bot bạn vừa tạo
2. Mở trình duyệt vào: `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Tìm `"chat":{"id":123456789` → số đó là `chat_id` của bạn

> Muốn bắn vào group: thêm bot vào group, nhắn 1 tin trong group rồi mở lại link
> `getUpdates`. `chat_id` của group là **số âm** (ví dụ `-1001234567890`).

---

## 2. Đưa code lên GitHub

**Nên để repo PUBLIC.** GitHub Actions miễn phí không giới hạn phút cho repo public, còn repo
private chỉ được 2000 phút/tháng — chạy 10 phút/lần tốn khoảng 10.000 phút/tháng, cháy quota
sau chưa tới một tuần. Secrets vẫn được che kín ở repo public, code này cũng không chứa gì
riêng tư. Nếu bắt buộc để private thì phải giãn cron lên 45–60 phút/lần.

```bash
cd mexc-watcher
git init
git add .
git commit -m "init: MEXC launchpool watcher"
git branch -M main
git remote add origin https://github.com/<username>/<repo>.git
git push -u origin main
```

---

## 3. Thêm secrets

Trong repo trên GitHub: **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token từ BotFather |
| `TELEGRAM_CHAT_ID` | chat_id của bạn |

---

## 4. Bật và chạy thử

1. Vào tab **Actions** → nếu thấy banner thì bấm **I understand my workflows, enable them**
2. Chọn workflow **MEXC Launchpool Watcher** → **Run workflow** để chạy tay lần đầu
3. Lần chạy đầu chỉ **ghi nhận** các bài đang có và gửi 1 tin "đã khởi động" —
   không spam hàng chục bài cũ. Từ lần sau chỉ báo bài **mới**.

Sau đó cron tự chạy **10 phút/lần**.

---

## Chạy thử ở máy (tuỳ chọn)

```bash
# xem kết quả mà không gửi Telegram
DRY_RUN=1 python mexc_watch.py

# gửi thật
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python mexc_watch.py
```

Chỉ cần Python 3.9+, không cần cài thư viện nào (dùng `urllib` sẵn có).

---

## Tuỳ chỉnh

**Đổi tần suất** — sửa dòng `cron` trong `.github/workflows/mexc-watch.yml`:

```yaml
- cron: "*/5 * * * *"    # 5 phút/lần (mức nhanh nhất GitHub cho phép)
- cron: "*/30 * * * *"   # 30 phút/lần
```

**Nguồn KuCoin** dùng API chính thức `api.kucoin.com/api/v3/announcements` — công khai, không
cần key, không bị Cloudflare chặn nên luôn chạy đường `direct`. Lọc theo từ khoá
`gempool | kumining | launchpool | burning drop | pool-x | staking mining | mining campaign | farming`
(KuCoin đổi tên sản phẩm khá thường xuyên nên danh sách này cố ý rộng). Tắt bằng `KUCOIN=0`,
đổi từ khoá bằng biến `KUCOIN_KEYWORDS`.

**Thêm/bớt nguồn MEXC** — sửa `SOURCES` trong `mexc_watch.py`:

```python
SOURCES = [
    ("Launchpool",  "/announcements/tag/launchpool-28", None),
    ("Airdrop+",    "/announcements/tag/airdrop-32",    None),
    ("Kickstarter", "/announcements/new-listings", re.compile(r"kickstarter|launchpool|airdrop", re.I)),
    # ("Pre-Market", "/announcements/tag/pre-market-29", None),
    # ("Earn",       "/announcements/tag/earn-26",       None),
]
```

Tham số thứ 3 là bộ lọc từ khoá (regex). `None` = lấy tất cả bài trong tag đó.

**Biến môi trường khác:**

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `MEXC_LANG` | `en-US` | đổi thành `vi-VN` để lấy trang tiếng Việt |
| `MAX_NOTIFY` | `10` | trần số tin mỗi lần chạy, chống spam nếu MEXC đổi HTML |
| `STATE_FILE` | `seen.json` | nơi lưu danh sách bài đã thấy |
| `DRY_RUN` | — | `1` = chỉ in ra màn hình, không gửi |
| `PROXY_MODE` | `auto` | `direct` = chỉ tải thẳng, `proxy` = chỉ đi qua proxy |
| `KUCOIN` | `1` | `0` = tắt theo dõi KuCoin GemPool |
| `KUCOIN_KEYWORDS` | `gempool\|kumining\|…` | regex lọc tiêu đề KuCoin |
| `FETCH_BUDGET` | `300` | số giây tối đa dành cho phần MEXC |

---

## Lưu ý quan trọng

- **MEXC không có API chính thức cho Launchpool.** API công khai (spot/futures v3) chỉ
  phục vụ giao dịch. Script này đọc trang thông báo — cách bền nhất hiện có, nhưng nếu
  MEXC đổi cấu trúc trang thì phải chỉnh lại regex `ARTICLE_RE`.
- **Cloudflare của MEXC chặn IP datacenter (đã xác nhận).** Chạy thẳng từ GitHub Actions
  trả về 403 Forbidden. Vì vậy script tự động đi vòng qua proxy đọc trang (`api.allorigins.win`,
  dự phòng `api.codetabs.com`) khi tải trực tiếp thất bại. Log sẽ in `(dang dung: allorigins)`
  cho biết đang đi đường nào. Trên máy cá nhân (IP nhà mạng) thì `direct` chạy được bình thường.
- **Proxy là bên thứ ba miễn phí, hay chập chờn.** Script thử lần lượt 4 proxy
  (`allorigins`, `codetabs`, `cors.lol`, `corsfix`), mỗi cái 2 lần. Lỗi 522/520 nghĩa là proxy
  đó đang quá tải — chuyện thường. Bỏ lỡ một lần chạy **không làm mất thông báo**: bài viết
  còn nằm trên trang MEXC nhiều ngày, lần chạy sau bắt lại. Với 144 lần chạy mỗi ngày thì chỉ
  cần một phần nhỏ thành công là đủ.
- **Trần thời gian `FETCH_BUDGET`** (mặc định 300 giây) giới hạn phần MEXC, để job không treo
  quá `timeout-minutes` của workflow. KuCoin luôn được quét trước vì nhanh và ổn định.
- Script **không bao giờ tự động tham gia** launchpool hay đặt lệnh. Nó chỉ đọc trang
  công khai và báo tin. Không cần API key MEXC, không đụng gì tới tài khoản của bạn.
- Nếu một lần gửi Telegram thất bại, bài đó **không** bị đánh dấu đã đọc — lần chạy sau
  sẽ thử gửi lại.

---

## Xử lý sự cố

| Triệu chứng | Cách xử lý |
|---|---|
| Không nhận được tin nào | Kiểm tra log ở tab Actions; xác nhận đã nhắn `/start` cho bot |
| Log: `thieu TELEGRAM_BOT_TOKEN` | Secrets đặt sai tên hoặc đặt nhầm ở Environment thay vì Repository |
| Log: `Khong lay duoc bai nao` | Cả tải thẳng lẫn 2 proxy đều hỏng — xem mục Lưu ý ở trên |
| Log: `403 Forbidden` ở dòng `direct` | Bình thường trên GitHub Actions, script tự chuyển qua proxy |
| Cron không chạy | GitHub tự tắt schedule nếu repo không hoạt động 60 ngày — vào bấm **Run workflow** để bật lại |
| Muốn reset, nhận lại từ đầu | Xoá nội dung `seen.json` về `{"seen":{},"initialized":false}` rồi commit |
