# Yerel doğrulama — 6 Ekim 2026

- Ana ortam: Python 3.12.10, FastMCP 3.4.0, ChromaDB 1.5.9,
  Sentence Transformers 6.0.0.
- Aktif PDF motoru ayrı ve temiz `.marker-venv` ortamında: marker-pdf 1.10.1,
  surya-ocr 0.17.1, torch 2.7.1, transformers 4.57.6.
  Bu ortam sistem paketlerini kullanmıyor; `pip check` başarılı.
- Gerçek `PdfConverter`, `create_model_dict` ve `save_output` API importları başarılı.
  Motor Surya/PyTorch üzerinden çalışıyor; llama-server, Ollama veya Docker kurulmadı
  ve gerekli değil. OCR korunuyor, isteğe bağlı LLM düzeltmesi kapalı.
- İndirilen `marker-master` (Marker 2) referans olarak korundu. Ana ortamda önceki
  Marker 2 paketi bulunabilir; üretim worker'ı `.env` içindeki ayrı Python'u kullanır.
  Worker yanlış Marker sürümünü model yüklemeden reddeder.
- 31 otomatik test geçti (son koşum 5,23 saniye). Gerçek Chroma/SQLite, süreç içi
  MCP ve ayrı süreç stdio MCP kullanılıyor. PDF dönüşümü ve embedding modelleri
  test çiftleriyle sınanıyor; bu çiftler üretim yolunda kullanılmıyor.
- Ruff kod ve biçim kontrolleri başarılı.
- Gerçek Marker modelleriyle iki sayfalık sentetik finans PDF'i dönüştürüldü.
  Dijital sayfadaki tablo Markdown'a geçti; `-1250.50`, `-1875.75` ve TRY birimi
  korundu. İkinci sayfada gömülü metin bulunmadığı ayrıca doğrulandı; gerçek OCR,
  `CREDITSCAN42`, `100000.00` ve `900.00` değerlerini doğru çıkardı. Fiziksel PDF
  sayfa sınırları 1 ve 2 olarak doğrulandı. Sonuç: `data/acceptance/ocr-report.json`.
- İlk model indirmesi C: üzerinde alan yetersizliğiyle kesildi. Model önbelleği ve
  Marker geçici indirme dosyaları `.env` içindeki `FINRAG_MODEL_CACHE_DIR` ile
  `E:/finance-rag-cache` altına yönlendirildi; gerçek Marker koşumu bu yolda tamamlandı.
- E5 model indirmesinde Xet reconstruction adresi bağlantı zaman aşımına uğradı.
  `FINRAG_EMBEDDING_DISABLE_XET=true` ile standart HTTPS yolu da denendi;
  yönlendirilen ağırlık adresine bağlantı yine zaman aşımına uğradı. Tanılama süreçleri
  durduruldu. Başka embedding modeli veya sahte vektör kullanılmadı.
- Bu nedenle gerçek E5 -> Chroma indeksleme ve Türkçe/anlamsal MCP araması henüz
  doğrulanmadı. `scripts/verify_real_pdf.py` ağ erişimi sağlandığında kontrolü yeniden
  çalıştırır ve başarılıysa `data/acceptance/acceptance-report.json` üretir. Geçerli bir
  başarılı kabul raporu henüz yok. Küçük sentetik örnek genel OCR kalite ölçümü değildir.
- Ana `.venv` mevcut sistem Python paketlerini de kullanıyor; ana ortamın tamamen
  bağımsız temiz kurulumu doğrulanmadı. `uv lock` registry erişim zaman aşımına uğradı;
  geçerli lock dosyası yok. Çalışma ortamı pip ile kuruldu.
- Claude JSON ve ChatGPT yerel TOML profillerinin önceki gerçek stdio kontrollerinde
  9 araç listelendi; `pdf_list` ve `pdf_health` başarıyla çağrıldı.
- ChatGPT Desktop/Codex yerel kaydı `C:/Users/musta/.codex/config.toml` içinde.
  Önceki dosyanın yedeği `config.toml.20260930T145152226127Z.bak`.
  `codex mcp get finance-rag --json` kaydı etkin stdio sunucusu olarak doğruladı.
- Güncel kontrolde bu yapılandırmayla çalışan bir sunucu süreci bulundu. Aynı veri
  klasöründe ikinci sunucu başlatılması beklendiği gibi dosya kilidiyle reddedildi.
  Uygulama içinden araç çağrısı henüz doğrulanmadı; bu sohbetin araç kataloğunda
  finance-rag araçları bulunmuyor.
- Açık bağlantıyı bozmadan kontrol etmek için bağlantı scriptine `--isolated`
  seçeneği eklendi. Güncel kullanıcı yapılandırmasıyla bu kontrol başarılı:
  9 araç, `pdf_list` ve `pdf_health` doğrulandı; Marker ortamı `installed` döndürdü.
  Kontrol geçici boş kütüphane kullanır; uygulamadaki araç etkinliğini kanıtlamaz.
- Marker alt süreçlerinin standart girdisi MCP kanalından ayrıldı. Windows'ta
  stdio içinden paket kontrolünde görülen zaman aşımı bu değişiklikle giderildi.
- Claude Desktop profili hazır; Claude'un kullanıcı ayarlarına henüz kurulmadı.

Çalıştırılan kontroller:

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src scripts tests
.venv/Scripts/python.exe -m ruff format --check src scripts tests
.marker-venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -m finance_rag.cli doctor
.venv/Scripts/python.exe scripts/check_desktop_connection.py C:/Users/musta/.codex/config.toml --isolated
```
