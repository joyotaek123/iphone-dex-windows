# iPhone DeX for Windows — Binary Communication Protocol (`IDEX v1`)

Dokumen ini mendefinisikan kontrak paket data biner antara **iOS Host** (`/ios-host`) dan **Windows Client** (`/windows-client`). Seluruh komunikasi berjalan di atas satu koneksi **TCP** persisten (default port `29480`) melalui **USB (`usbmuxd`)** maupun **TCP lokal / LAN** untuk pengujian.

> **Aturan Byte Order:** Seluruh field multi-byte (`uint16`, `uint32`, `uint64`, `float32`) menggunakan **Big-Endian (Network Byte Order)**.

---

## 1. Alur Handshake & Streaming

```
Windows Client                                       iOS Host (Port 29480)
      |                                                       |
      |--- [TCP Connect via usbmuxd / localhost] ------------>|
      |--- 0x01 HELLO (preferred res, fps, codec) ----------->|
      |<-- 0x02 HELLO_ACK (actual 1920x1080, fps, codec) -----|
      |                                                       |
      |<== 0x10 VIDEO_FRAME (JPEG / H.264 Annex-B) ===========| (30–60 FPS)
      |--- 0x20 MOUSE_MOVE (norm_x, norm_y) ----------------->|
      |--- 0x21 MOUSE_BUTTON (norm_x, norm_y, btn, action) -->|
      |--- 0x22 MOUSE_SCROLL (norm_x, norm_y, dx, dy) ------->|
      |--- 0x23 KEY_EVENT (key_code, action, mods, char) ---->|
      |                                                       |
      |--- 0x30 PING (timestamp_us) ------------------------->| (RTT check)
      |<-- 0x31 PONG (timestamp_us) --------------------------|
```

---

## 2. Format Header Paket (12 Bytes Tetap)

Setiap paket diawali dengan header tepat **12 byte** (`struct` format: `>4sBBHI`).

| Offset | Panjang | Tipe | Field | Deskripsi |
| :--- | :--- | :--- | :--- | :--- |
| `0` | 4 byte | `char[4]` | `magic` | Identifier tetap ASCII `"IDEX"` (`0x49 0x44 0x45 0x58`). |
| `4` | 1 byte | `uint8` | `version` | Versi protokol saat ini: `0x01`. |
| `5` | 1 byte | `uint8` | `msg_type` | Kode tipe pesan (lihat tabel di bawah). |
| `6` | 2 byte | `uint16` | `flags` | Bitmask flag paket (contoh: `0x0001` = Keyframe / IDR). |
| `8` | 4 byte | `uint32` | `payload_len` | Panjang payload setelah header dalam byte (maks `16_777_216` / 16 MB). |

Total ukuran paket = `12 + payload_len` byte.

---

## 3. Daftar `msg_type` & Flag

| Kode | Nama | Arah | Deskripsi |
| :--- | :--- | :--- | :--- |
| `0x01` | `HELLO` | Client → Host | Negosiasi resolusi target, FPS, dan codec preferensi. |
| `0x02` | `HELLO_ACK` | Host → Client | Konfirmasi parameter kanvas desktop aktif dari iOS Host. |
| `0x10` | `VIDEO_FRAME` | Host → Client | Satu frame video desktop 16:9 (JPEG atau H.264 Annex-B). |
| `0x20` | `MOUSE_MOVE` | Client → Host | Posisi kursor mouse ternormalisasi `[0.0, 1.0]`. |
| `0x21` | `MOUSE_BUTTON` | Client → Host | Event klik / lepas tombol mouse di koordinat ternormalisasi. |
| `0x22` | `MOUSE_SCROLL` | Client → Host | Event scroll wheel horizontal & vertikal. |
| `0x23` | `KEY_EVENT` | Client → Host | Event tekan / lepas tombol keyboard + karakter UTF-16. |
| `0x30` | `PING` | Client ↔ Host | Mengukur latensi (RTT) dengan timestamp mikrodetik. |
| `0x31` | `PONG` | Client ↔ Host | Balasan `PING` dengan timestamp asli tanpa diubah. |

### Flag Header (`flags`)
- `0x0000`: Paket normal.
- `0x0001` (`FLAG_KEYFRAME`): Khusus `VIDEO_FRAME`, menandakan frame kunci (selalu `1` untuk JPEG, dan `1` untuk IDR + SPS/PPS pada H.264).

### Kode Codec (`preferred_codec` / `active_codec`)
- `0x01` (`CODEC_JPEG`): Frame JPEG lengkap per paket (default Phase 1 PoC, 0 setup decoder tambahan).
- `0x02` (`CODEC_H264_ANNEXB`): Byte-stream H.264 Annex-B (`0x00000001` start code) dari VideoToolbox iOS.

---

## 4. Spesifikasi Payload per Tipe Pesan

### 4.1 `0x01` — `HELLO` (8 Bytes, `>HHBBH`)
| Offset | Panjang | Tipe | Field | Deskripsi |
| :--- | :--- | :--- | :--- | :--- |
| `0` | 2 byte | `uint16` | `client_width` | Lebar layar target yang diminta client (mis. `1920`). |
| `2` | 2 byte | `uint16` | `client_height` | Tinggi layar target yang diminta client (mis. `1080`). |
| `4` | 1 byte | `uint8` | `target_fps` | FPS yang diinginkan (`1..120`, mis. `30` atau `60`). |
| `5` | 1 byte | `uint8` | `preferred_codec` | `0x01` (JPEG) atau `0x02` (H.264 Annex-B). |
| `6` | 2 byte | `uint16` | `reserved` | Diset `0x0000` untuk alignment / ekspansi masa depan. |

### 4.2 `0x02` — `HELLO_ACK` (8 Bytes, `>HHBBH`)
| Offset | Panjang | Tipe | Field | Deskripsi |
| :--- | :--- | :--- | :--- | :--- |
| `0` | 2 byte | `uint16` | `canvas_width` | Lebar kanvas aktual di iOS Host (Phase 1: `1920`). |
| `2` | 2 byte | `uint16` | `canvas_height` | Tinggi kanvas aktual di iOS Host (Phase 1: `1080`). |
| `4` | 1 byte | `uint8` | `actual_fps` | FPS aktual yang digunakan encoder. |
| `5` | 1 byte | `uint8` | `active_codec` | `0x01` (JPEG) atau `0x02` (H.264 Annex-B). |
| `6` | 2 byte | `uint16` | `status` | `0` = OK, non-zero = kode error penolakan koneksi. |

### 4.3 `0x10` — `VIDEO_FRAME` (18 Bytes Sub-Header + Raw Frame Data, `>IQBBHH`)
| Offset | Panjang | Tipe | Field | Deskripsi |
| :--- | :--- | :--- | :--- | :--- |
| `0` | 4 byte | `uint32` | `frame_seq` | Nomor urut frame monoton (`0, 1, 2, ...`). |
| `4` | 8 byte | `uint64` | `timestamp_us` | Timestamp pengambilan frame dalam mikrodetik. |
| `12` | 1 byte | `uint8` | `codec` | `0x01` (JPEG) atau `0x02` (H.264 Annex-B). |
| `13` | 1 byte | `uint8` | `reserved` | Diset `0x00`. |
| `14` | 2 byte | `uint16` | `width` | Lebar frame video (mis. `1920`). |
| `16` | 2 byte | `uint16` | `height` | Tinggi frame video (mis. `1080`). |
| `18` | `N` byte | `bytes` | `frame_data` | Data biner frame (`N = payload_len - 18`). |

### 4.4 `0x20` — `MOUSE_MOVE` (8 Bytes, `>ff`)
| Offset | Panjang | Tipe | Field | Deskripsi |
| :--- | :--- | :--- | :--- | :--- |
| `0` | 4 byte | `float32` | `norm_x` | Posisi horizontal ternormalisasi `0.0` (kiri) s.d. `1.0` (kanan). |
| `4` | 4 byte | `float32` | `norm_y` | Posisi vertikal ternormalisasi `0.0` (atas) s.d. `1.0` (bawah). |

### 4.5 `0x21` — `MOUSE_BUTTON` (10 Bytes, `>ffBB`)
| Offset | Panjang | Tipe | Field | Deskripsi |
| :--- | :--- | :--- | :--- | :--- |
| `0` | 4 byte | `float32` | `norm_x` | Posisi horizontal ternormalisasi `[0.0, 1.0]`. |
| `4` | 4 byte | `float32` | `norm_y` | Posisi vertikal ternormalisasi `[0.0, 1.0]`. |
| `8` | 1 byte | `uint8` | `button` | `1` = Left, `2` = Right, `3` = Middle. |
| `9` | 1 byte | `uint8` | `action` | `0` = Button Up (lepas), `1` = Button Down (tekan). |

### 4.6 `0x22` — `MOUSE_SCROLL` (16 Bytes, `>ffff`)
| Offset | Panjang | Tipe | Field | Deskripsi |
| :--- | :--- | :--- | :--- | :--- |
| `0` | 4 byte | `float32` | `norm_x` | Posisi horizontal kursor saat scroll `[0.0, 1.0]`. |
| `4` | 4 byte | `float32` | `norm_y` | Posisi vertikal kursor saat scroll `[0.0, 1.0]`. |
| `8` | 4 byte | `float32` | `delta_x` | Pergeseran scroll horizontal (satuan notch/tick). |
| `12` | 4 byte | `float32` | `delta_y` | Pergeseran scroll vertikal (`+` ke atas, `-` ke bawah). |

### 4.7 `0x23` — `KEY_EVENT` (8 Bytes, `>IBBH`)
| Offset | Panjang | Tipe | Field | Deskripsi |
| :--- | :--- | :--- | :--- | :--- |
| `0` | 4 byte | `uint32` | `key_code` | Virtual key code Windows (`vk` / `keycode`) atau HID usage ID. |
| `4` | 1 byte | `uint8` | `action` | `0` = Key Up, `1` = Key Down. |
| `5` | 1 byte | `uint8` | `modifiers` | Bitmask: `1` = Shift, `2` = Ctrl, `4` = Alt, `8` = Meta/Win. |
| `6` | 2 byte | `uint16` | `unicode_char` | Kode karakter UTF-16 (`0` jika tombol non-karakter seperti Shift/Arrow). |

### 4.8 `0x30` `PING` & `0x31` `PONG` (8 Bytes, `>Q`)
| Offset | Panjang | Tipe | Field | Deskripsi |
| :--- | :--- | :--- | :--- | :--- |
| `0` | 8 byte | `uint64` | `timestamp_us` | Timestamp pengirim dalam mikrodetik. |

---

## 5. Penanganan Stream TCP (Framing & Validasi)

1. Karena TCP bersifat stream-oriented, penerima **wajib** melakukan buffering hingga minimal 12 byte tersedia untuk membaca header, lalu membaca hingga `payload_len` byte penuh terkumpul.
2. Jika `magic != "IDEX"` atau `version != 0x01` atau `payload_len > 16_777_216`, koneksi harus langsung ditutup untuk mencegah desinkronisasi buffer atau konsumsi memori berlebih.
3. Koordinat mouse dari Windows (`norm_x`, `norm_y`) harus di-clamp ke `[0.0, 1.0]` sebelum dikirim, dan pada sisi iOS dikonversi ke koordinat piksel kanvas via `x = norm_x * canvas_width`, `y = norm_y * canvas_height`.
