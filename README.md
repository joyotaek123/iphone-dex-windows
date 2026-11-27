# iPhone DeX for Windows

Proyek open-source untuk mengubah iPhone menjadi PC desktop **16:9 (1920x1080)** ala Samsung DeX di layar Windows melalui kabel USB (`usbmuxd`), **tanpa perlu Jailbreak**.

---

## Arsitektur Monorepo

```
iphone-dex-windows/
├── PROTOCOL.md                     # Kontrak paket data biner IDEX v1 (TCP port 29480)
├── .github/workflows/
│   └── build-ios-ipa.yml           # GitHub Actions macOS runner -> compile & package .ipa
├── ios-host/                       # Aplikasi Host iOS (Swift 5.9 + UIKit + VideoToolbox + NWListener)
├── windows-client/                 # Aplikasi desktop Windows ringan (Python + Tkinter + Pillow + FFmpeg)
└── tools/mock-ios-host/            # Simulator lokal iOS Host di Windows untuk uji coba cepat tanpa iPhone
```

### Pilihan Tech Stack
- **`/ios-host` (Swift + UIKit + VideoToolbox + Network.framework + XcodeGen)**: Menggunakan `project.yml` agar GitHub Actions di macOS otomatis membuat proyek Xcode dan mem-build file `.ipa` tanpa konflik `.pbxproj`.
- **`/windows-client` (Python 3 + Tkinter + Pillow + FFmpeg + `pymobiledevice3`)**: Dipilih agar sangat ringan di PC Windows (tanpa perlu install Visual Studio C++ / Rust / .NET SDK berukuran gigabyte), bisa langsung terhubung ke USB iPhone & mengaktifkan JIT via `pymobiledevice3`, serta mudah dibungkus menjadi `.exe` memakai PyInstaller.

---

## Rencana Pengerjaan Bertahap (Roadmap)

- [x] **Phase 1 — Proof of Concept (Aktif Sekarang):**
  - Kontrak komunikasi biner `PROTOCOL.md`.
  - GitHub Actions macOS build pipeline untuk menghasilkan `iPhoneDeXHost-unsigned.ipa`.
  - `/ios-host` PoC: kanvas desktop 16:9 (`1920x1080`), 1 jendela interaktif yang bisa digeser & diklik, server TCP port `29480`, encoder JPEG + fondasi VideoToolbox H.264.
  - `/windows-client` PoC: viewer 16:9 responsif yang menampilkan video stream dan mengirim klik mouse, scroll, serta ketikan keyboard kembali ke host.
  - `/tools/mock-ios-host`: simulator host lokal di Windows untuk verifikasi end-to-end tanpa menunggu build iPhone.
- [ ] **Phase 2 — Transport USB `usbmuxd`, Auto-JIT & H.264 60 FPS:**
  - Tunneling otomatis USB via `pymobiledevice3` (tanpa Wi-Fi) + aktivasi JIT otomatis untuk iOS 17+.
  - Mengaktifkan stream `CODEC_H264_ANNEXB` hardware-encoded 60 FPS dari `VideoToolbox` ke decoder `ffmpeg`/GPU di Windows.
- [ ] **Phase 3 — Host Container Multi-Window (LiveContainer / iDesk Architecture):**
  - Memuat file `.ipa` lain ke dalam `DesktopCanvasView` sebagai jendela melayang multi-window dengan manajemen fokus, resize, dan taskbar aktif.
- [ ] **Phase 4 — Audio Routing, Clipboard Sync & Native Renderer:**
  - Sinkronisasi audio PCM/AAC ke speaker Windows, clipboard dua arah, serta opsi renderer Direct3D/OpenGL.

---

## Cara Menjalankan Uji Coba Phase 1 di Windows

### 1. Uji Coba Lokal dengan Simulator (Tanpa iPhone)
Pastikan Python 3 dan library `pillow` sudah terpasang:
```powershell
cd iphone-dex-windows
python -m pip install -r windows-client/requirements.txt
```

Buka **Terminal 1** (menjalankan Simulator Host iOS):
```powershell
python tools/mock-ios-host/mock_ios_host.py
```

Buka **Terminal 2** (menjalankan Aplikasi Windows Client):
```powershell
python windows-client/src/main.py --mode tcp --host 127.0.0.1 --port 29480
```
*(Atau cukup klik dua kali `tools/mock-ios-host/run_mock_host.bat` lalu `windows-client/run_client.bat`.)*

### 2. Menjalankan Unit & Integration Test
```powershell
cd iphone-dex-windows
python -m unittest discover -s windows-client/tests -v
```

### 3. Build `.ipa` Otomatis via GitHub Actions
Push folder `iphone-dex-windows` ke repository GitHub Anda, lalu buka tab **Actions** -> **Build iOS Host IPA** -> jalankan workflow (atau otomatis saat push ke `ios-host/**`). File `iPhoneDeXHost-unsigned.ipa` dapat diunduh dari bagian **Artifacts** dan di-sideload ke iPhone menggunakan AltStore / SideStore / Sideloadly.
