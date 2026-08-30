# Pool Watcher → Telegram

Báo khi có **pool mới mở** để đem token đang giữ đi farm. Chạy miễn phí trên GitHub Actions,
không cần bật máy.

| Sàn | Sự kiện theo dõi | Token bạn bỏ vào | Nguồn dữ liệu |
|---|---|---|---|
| MEXC | Launchpool, Kickstarter, buyback & burn | MX | cào HTML (qua proxy) |
| KuCoin | KuMining, GemPool | KCS | API chính thức |
| HTX | Primepool, Primelist | HTX / HT | cào HTML (trực tiếp) |
| CoinEx | sự kiện liên quan CET | CET | API Zendesk |

Bot còn **mở bài ra đọc** để lấy giờ mở/đóng pool rồi **nhắc trước khi pool mở** và
**nhắc trước khi pool đóng** để kịp rút token về, và **tự báo khi chính nó hỏng** thay vì
im lặng khiến bạn tưởng đang không có pool nào.

Kèm theo là **bộ theo dõi burn** (`burn_watch.py`): báo mỗi khi sàn đốt token, kèm tổng đã
đốt, đốt hôm nay và số còn lại của MX / KCS / HTX / CET — xem mục
[Theo dõi burn token sàn](#5-theo-dõi-burn-token-sàn).

Cố ý **không** theo dõi tin niêm yết coin mới, Airdrop+ hay khuyến mãi giao dịch — chỉ những
sự kiện mà bạn bỏ token đang giữ vào để nhận thưởng.

> **Về CoinEx:** sàn này **không có sản phẩm launchpool**. Mục Events của họ chủ yếu là thưởng
> nạp tiền, khuyến mãi mua fiat và thi giao dịch. Lợi tức của CET đến từ CoinEx Staking —
> một sản phẩm chạy thường trực, không phải sự kiện có hạn. Nên bộ lọc CoinEx bám vào chữ
> `CET` để bắt các sự kiện liên quan token bạn giữ, chứ không kỳ vọng có pool.

> **Về HTX Primepool:** sản phẩm này có thật (khoá $HTX để farm token mới) nhưng đợt gần đây
> không thấy chạy — các mục Latest Activities và HTX Earn vài tháng qua chỉ toàn khuyến mãi
> giao dịch. Bot cứ theo dõi sẵn, khi nào Primepool quay lại là báo.

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
| `ETHERSCAN_API_KEY` | *(tuỳ chọn)* key miễn phí từ [etherscan.io/apis](https://etherscan.io/apis) — để đọc cung MX/KCS thẳng từ blockchain |
| `COINGECKO_API_KEY` | *(tuỳ chọn)* Demo key miễn phí từ [coingecko.com/en/api](https://www.coingecko.com/en/api) — đỡ bị chặn 429 |

Hai key cuối chỉ phục vụ phần theo dõi burn. Thiếu chúng bot vẫn chạy: `ETHERSCAN_API_KEY`
thiếu thì lấy số của CoinGecko, `COINGECKO_API_KEY` thiếu thì gọi CoinGecko không key
(vẫn được, chỉ dễ dính giới hạn tần suất hơn).

---

## 4. Bật và chạy thử

1. Vào tab **Actions** → nếu thấy banner thì bấm **I understand my workflows, enable them**
2. Chọn workflow **MEXC Launchpool Watcher** → **Run workflow** để chạy tay lần đầu
3. Lần chạy đầu chỉ **ghi nhận** các bài đang có và gửi 1 tin "đã khởi động" —
   không spam hàng chục bài cũ. Từ lần sau chỉ báo bài **mới**.

Sau đó cron tự chạy **10 phút/lần**.

---

## 5. Theo dõi burn token sàn

`burn_watch.py` chạy chung workflow, mỗi giờ một lần đọc **tổng cung** hiện tại của 4 token
và so với lần trước. Cung giảm = sàn vừa đốt token → bắn tin ngay.

**Hai loại tin:**

*Khi sàn vừa đốt:*

```
🔥 MEXC vua burn MX

Dot nay: 12.500M MX (~$27.63M)
Tong da dot: 603.475M / 1.000B (60.35%)
Con lai: 396.525M MX
██████░░░░
```

*Tổng kết định kỳ (mặc định sáng thứ Hai, 8h giờ VN):*

```
📊 Tong ket burn token san
30/08/2026

🔥 MX · MEXC
   Con lai: 396.525M / 1.000B
   Da dot: 603.475M (60.35%) ██████░░░░
   Hom nay: 79,305 · 7 ngay: 1.850M · 30 ngay: 7.930M
   nguon: on-chain
...
```

**Nguồn số liệu** — on-chain trước, CoinGecko dự phòng:

| Token | Cung ban đầu | Nguồn chính | Vì sao |
|---|---|---|---|
| MX | 1.000.000.000 | on-chain, Etherscan V2 | toàn bộ cung nằm trên 1 contract ERC-20 |
| KCS | 200.000.000 | on-chain, Etherscan V2 | như trên |
| HTX | 999,99 nghìn tỷ | CoinGecko | token trải trên TRON + Ethereum + BSC |
| CET | 10.000.000.000 | CoinGecko | cung thật nằm trên CoinEx Chain, ERC-20 chỉ là phần cầu nối |

Contract dùng để đọc on-chain:

- MX — `0x11eeF04c884E24d9B7B4760e7476D06ddF797f36` (Ethereum)
- KCS — `0xf34960d9d60be18cC1D5Afc1A6F012A723a28811` (Ethereum)

Sửa danh sách token, cung ban đầu hoặc contract trong biến `TOKENS` ở đầu `burn_watch.py`.

> **Con số "đã đốt" là ước tính**, tính bằng `cung ban đầu − tổng cung hiện tại`. Nó khớp với
> số sàn công bố khi sàn burn bằng cách **giảm thật** tổng cung (MX, KCS đúng như vậy). Với
> token burn bằng cách gửi vào ví chết, con số phụ thuộc cách CoinGecko thống kê nên có thể
> lệch chút so với thông cáo của sàn. Đừng dùng làm số liệu kế toán.

**Biến môi trường của phần burn:**

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `BURN_WATCH` | `1` | `0` = tắt hẳn phần theo dõi burn |
| `BURN_TOKENS` | — | chỉ theo dõi vài token, vd `MX,KCS` |
| `BURN_INTERVAL_MIN` | `60` | tối thiểu bao nhiêu phút mới kiểm tra lại (workflow chạy 10 phút/lần nên script tự bỏ qua các lượt thừa) |
| `BURN_MIN_PCT` | `0.005` | bỏ qua thay đổi nhỏ hơn % này — chặn nhiễu làm tròn |
| `BURN_DIGEST_DAY` | `mon` | ngày gửi tổng kết: `mon`…`sun`, `daily`, hoặc `off` |
| `BURN_DIGEST_HOUR_UTC` | `1` | giờ UTC gửi tổng kết (1 = 8h sáng giờ VN) |
| `BURN_STATE_FILE` | `burn.json` | nơi lưu snapshot cung theo ngày |
| `ETHERSCAN_API_KEY` | — | thiếu thì bỏ qua đường on-chain |
| `COINGECKO_API_KEY` | — | Demo key, gắn vào query `x_cg_demo_api_key` |

Lần chạy đầu chỉ **ghi nhận** cung hiện tại và gửi 1 tin tóm tắt, không báo burn giả.
`burn.json` được commit ngược về repo giống `seen.json` — đây cũng là nơi lưu lịch sử cung
theo ngày (giữ 40 ngày gần nhất) để tính được "hôm nay / 7 ngày / 30 ngày".

---

## 6. Đọc chi tiết bài và nhắc lịch pool

Trang danh sách chỉ có tiêu đề. Mọi thứ quan trọng — pool mở lúc nào, đóng lúc nào, thưởng
bao nhiêu — nằm trong thân bài. Với mỗi bài **mới**, bot mở bài ra một lần và bóc ra
(`article.py`):

```
🚀 MEXC Launchpool
📅 30/08/2026

KSKD Launchpool: Share 10,000,000 KSKD!

🕐 Mo 12:44 02/09 · Dong 12:44 02/10 (gio VN)
🎁 Thuong: 10,000,000 KSKD
```

Có giờ rồi thì bot nhắc được — đây mới là phần đáng giá, vì thông báo thường ra **trước**
1–3 ngày, tới lúc pool mở thật thì đã quên:

```
⏰ Pool sap mo - con 24 phut          ⚠️ Pool sap dong - con 5 gio 19 phut

KSKD Launchpool: Share 10,000,000     EMBLEM Launchpool: Share 5,000,000
                                       Nho rut token ve.
🕐 Mo luc 13:09 30/08 (gio VN)        🕐 Dong luc 18:04 30/08 (gio VN)
```

Lịch lưu trong `seen.json` mục `agenda`, pool đóng quá 3 ngày thì tự dọn.

Bộ bóc thời gian hiểu các định dạng: `May 25, 2026, 13:00 (UTC)` (MEXC),
`2026-05-25 21:00 (UTC+8)` (KuCoin/HTX), `25 May 2026 13:00`, `25/05/2026 13:00`. Nhiều sàn
chỉ ghi múi giờ **một lần** cho cả khoảng — bot lấy múi giờ đó áp cho mốc còn thiếu. Ngày kiểu
`05/06/2026` không đoán được đâu là ngày đâu là tháng thì bot **bỏ qua** chứ không đoán bừa.

> Bóc sai còn tệ hơn không bóc, nên bot chỉ nhận khoảng thời gian khi tìm được **ít nhất 2
> mốc** và khoảng cách giữa chúng nằm trong 1 giờ – 200 ngày. Không chắc thì bỏ trống, tin
> báo pool vẫn gửi bình thường, chỉ là không có dòng 🕐.

---

## 7. Cảnh báo khi chính bot hỏng

Đây là lỗ hổng nguy hiểm nhất của loại bot này: **hỏng im lặng trông y hệt "không có pool nào"**.
Bot tự canh hai kiểu hỏng.

**Không tải được nguồn nào** — Cloudflare chặn IP hoặc proxy chết hết. Sau 6 lần chạy liên
tiếp thất bại (~1 tiếng) bot bắn một tin cảnh báo, và bắn tin báo hồi phục khi chạy lại được.

**Tải được nhưng bóc ra 0 bài** — sàn đổi cấu trúc HTML, regex không còn khớp. Kiểu này
nguy hiểm hơn: GitHub Actions vẫn xanh, log vẫn đẹp, nhưng bot mù tịt. Bot đếm số bài bóc
được **trước khi lọc từ khoá**; tải thành công mà con số đó bằng 0 ba lần liên tiếp thì báo:

```
⚠️ Nguon MEXC Launchpool co the da hong

Tai trang thanh cong 3 lan lien tiep nhung khong boc duoc bai nao.
Nhieu kha nang san doi cau truc HTML, can sua lai regex.
```

Mỗi cảnh báo chỉ gửi **một lần** cho tới khi tình trạng đổi, không spam. Tắt bằng `HEALTH_ALERT=0`.

> Cố ý đếm bài **trước** khi lọc từ khoá. Nếu đếm sau, HTX vài tháng không có Primepool sẽ bị
> báo nhầm là hỏng.

---

## Chạy thử ở máy (tuỳ chọn)

```bash
# xem kết quả mà không gửi Telegram
DRY_RUN=1 python mexc_watch.py

# gửi thật
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python mexc_watch.py

# phần burn (BURN_INTERVAL_MIN=0 để chạy ngay, không đợi ngưỡng 60 phút)
DRY_RUN=1 BURN_INTERVAL_MIN=0 python burn_watch.py

# xem thử tin tổng kết
DRY_RUN=1 BURN_INTERVAL_MIN=0 BURN_DIGEST_DAY=daily BURN_DIGEST_HOUR_UTC=0 python burn_watch.py
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
cần key, không bị Cloudflare chặn nên luôn chạy đường `direct`. Chỉ quét mục `activities`, lọc theo từ khoá
`gempool | kumining | launchpool | burning drop | pool-x | staking mining | mining campaign`
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
| `MAX_AGE_HOURS` | `72` | bỏ qua bài cũ hơn ngưỡng này; `0` = tắt lọc theo ngày |
| `TITLE_DEDUPE_DAYS` | `30` | chặn bài trùng tiêu đề trong khoảng này; `0` = tắt |
| `STATE_FILE` | `seen.json` | nơi lưu danh sách bài đã thấy |
| `DRY_RUN` | — | `1` = chỉ in ra màn hình, không gửi |
| `PROXY_MODE` | `auto` | `direct` = chỉ tải thẳng, `proxy` = chỉ đi qua proxy |
| `KUCOIN` | `1` | `0` = tắt theo dõi KuCoin |
| `HTX` | `1` | `0` = tắt theo dõi HTX |
| `COINEX` | `1` | `0` = tắt theo dõi CoinEx |
| `HTX_KEYWORDS` | `primepool\|primelist\|…` | regex lọc tiêu đề HTX |
| `COINEX_KEYWORDS` | `\bCET\b\|launchpool\|…` | regex lọc tiêu đề CoinEx |
| `HTX_BUDGET` | `120` | số giây tối đa dành cho phần HTX |
| `KUCOIN_KEYWORDS` | `gempool\|kumining\|…` | regex lọc tiêu đề KuCoin |
| `FETCH_BUDGET` | `300` | số giây tối đa dành cho phần MEXC |

**Đọc chi tiết bài và nhắc lịch:**

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ARTICLE_DETAIL` | `1` | `0` = không mở bài lấy giờ mở/đóng, chỉ báo tiêu đề như cũ |
| `ARTICLE_BUDGET` | `60` | số giây tối đa dành cho việc mở bài mỗi lần chạy |
| `REMIND_START_MIN` | `30` | nhắc trước bao nhiêu phút khi pool sắp mở |
| `REMIND_END_HOURS` | `6` | nhắc trước bao nhiêu giờ khi pool sắp đóng |
| `MAX_REMINDERS` | `5` | trần số tin nhắc mỗi lần chạy |
| `DISPLAY_TZ_HOURS` | `7` | múi giờ hiển thị trong tin nhắn (7 = giờ VN) |

**Tin burn và cảnh báo sức khoẻ:**

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `BURN_NEWS` | `1` | `0` = không bắt thông báo buyback/burn của sàn |
| `BURN_NEWS_KEYWORDS` | `buyback\|repurchase\|burn\|…` | regex nhận diện tin burn |
| `HEALTH_ALERT` | `1` | `0` = tắt cảnh báo khi bot hỏng |
| `HEALTH_DOWN_AFTER` | `6` | báo sau bao nhiêu lần liên tiếp không tải được nguồn nào |
| `HEALTH_PARSE_AFTER` | `3` | báo sau bao nhiêu lần tải được mà bóc 0 bài |

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
- **Chặn trùng theo tiêu đề, không chỉ theo ID.** Sàn sửa bài rồi cấp ID mới, hoặc cùng một
  bài đăng ở hai danh mục với đường dẫn khác nhau — dedupe theo ID sẽ trượt. Nên `seen.json`
  lưu thêm bảng `titles`: tiêu đề đã chuẩn hoá kèm thời điểm đã báo, chặn trong `TITLE_DEDUPE_DAYS`
  ngày. Chuẩn hoá **giữ lại chữ số và dấu `#`**, vì "PrimePool #39" và "#40" là hai sự kiện khác
  nhau. Có giới hạn thời gian để sự kiện định kỳ trùng tên (chạy lại sau vài tháng) vẫn báo được.
- **Chỉ báo bài mới trong vòng 72 giờ.** Ngoài việc so với `seen.json`, script còn đọc ngày
  đăng và bỏ qua bài cũ hơn `MAX_AGE_HOURS`. Đây là lưới an toàn: nếu `seen.json` bị xoá hay
  reset, bot sẽ không dội một loạt pool đã đóng từ đời nào. Bài nào **không đọc được ngày**
  thì vẫn giữ — thà báo thừa còn hơn bỏ sót.
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
