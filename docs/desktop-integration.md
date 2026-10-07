# ChatGPT Desktop ve Claude Desktop bağlantısı

30 Eylül 2026 tarihli resmî dokümanlara göre iki istemcinin **yerel** MCP bağlantısı
için aynı Python sunucusu `stdio` ile çalıştırılabilir. Mevcut proje bu yolu kullanır.

## Claude Desktop

Hazır JSON: `examples/claude_desktop_config.json`.

1. Claude Desktop → Settings → Developer → Edit Config ile kullanılan dosyayı aç.
2. Aşağıdaki komutu bu proje dizininde çalıştır. Mevcut diğer sunucular korunur;
   dosya varsa değişiklikten önce tarihli `.bak` yedeği oluşturulur.
3. Claude Desktop'ı tamamen kapatıp yeniden aç; `finance-rag` araçlarını kontrol et.

```powershell
.venv/Scripts/python.exe scripts/configure_desktop.py --client claude --apply
```

Varsayılan yol `%APPDATA%/Claude/claude_desktop_config.json` dosyasıdır. Mevcut MSIX
sanallaştırılmış dosya bulunursa script onu seçer. Birden fazla dosya varsa seçim yapmaz.
Edit Config farklı bir dosya açıyorsa tam yolu açıkça ver:

```powershell
.venv/Scripts/python.exe scripts/configure_desktop.py --client claude --apply --config "C:/gercek/yol/claude_desktop_config.json"
```

İlk kurulumda henüz dosya yoksa uygulamanın Edit Config adımını önce tamamlamak,
özellikle Windows Store/MSIX kurulumlarında doğru hedefi belirlemeyi kolaylaştırır.
Bu yöntem Claude Desktop sohbetindeki yerel MCP bağlantısı içindir; Cowork/plugin
paketleme ile aynı kurulum değildir.

## ChatGPT Desktop — yerel çalışma ortamı

Hazır TOML: `examples/chatgpt_desktop.toml`.

Bu bilgisayardaki hazır profiller ve kurulu kayıt temiz Python ortamını
`E:/finance-rag-runtime/app-venv/Scripts/python.exe` kullanır. Farklı bir ortama
profil üretmek için `configure_desktop.py` komutuna `--python ".../python.exe"` ekle.

OpenAI Docs, ChatGPT Desktop ile Codex CLI/IDE'nin aynı yerel host için MCP
yapılandırmasını paylaştığını belirtiyor. Script yalnızca `mcp_servers.finance-rag`
bölümünü ekler; mevcut TOML içeriği ve diğer ayarlar korunur.

```powershell
.venv/Scripts/python.exe scripts/configure_desktop.py --client chatgpt --apply
```

Hedef `CODEX_HOME/config.toml`, ortam değişkeni yoksa `~/.codex/config.toml` dosyasıdır.
Uygulamada Settings → MCP servers üzerinden kaydı kontrol et, Restart kullan.
Yerel çalışma ortamında `/mcp` ile bağlantıyı incele.

Bu kayıt ChatGPT web/bulut sohbetine otomatik bağlanmaz. Hosted bağlantı için resmî
ayrı seçenekler HTTPS MCP endpoint'i veya Secure MCP Tunnel'dır; bu proje şu anda
HTTP endpoint'i yayımlamıyor. Desktop'ta yerel host seçilmelidir.

## Kullanım ve bağlantı kontrolü

İlk mesaj: **“finance-rag üzerinden pdf_health ve pdf_list çalıştır.”**

Uygulamada etkinleştirmeden önce gerçek stdio bağlantısını kontrol etmek için:

```powershell
.venv/Scripts/python.exe scripts/check_desktop_connection.py examples/claude_desktop_config.json
.venv/Scripts/python.exe scripts/check_desktop_connection.py examples/chatgpt_desktop.toml
```

Bu kontrolleri sırayla, istemcideki finance-rag bağlantısı kapalıyken çalıştır.
Protokol bağlantısını test eder; uygulamada etkinleştirme veya gerçek PDF/OCR testi yapmaz.

İstemci zaten çalışıyorsa `--isolated` ekle. Kontrol geçici boş bir kütüphane kullanır;
mevcut sunucuya ve belgelere dokunmaz, kontrol sonunda geçici klasörü temizler:

```powershell
.venv/Scripts/python.exe scripts/check_desktop_connection.py examples/chatgpt_desktop.toml --isolated
```

Dokuz araç görünmeli: `pdf_add`, `pdf_job_status`, `pdf_list`, `pdf_search`,
`pdf_search_similarity`, `pdf_search_keyword`, `pdf_get_page`, `pdf_remove`, `pdf_health`.
Boş kütüphanede `pdf_list` sıfır belge döndürür; model ağırlıkları yüklenmez.

PDF'leri önce `data/inbox` klasörüne koy. Sohbete PDF eklemek tek başına onu bu yerel
klasöre kopyalamaz. `pdf_add` için bilgisayardaki tam dosya yolunu ver.
İş kimliği döndükten sonra `pdf_job_status` ile tamamlanmasını izle.

İki istemciyi **aynı veri dizinine bağlı iki stdio sunucusuyla aynı anda açma**;
uygulama ikinci sunucuyu veri tutarlılığı için reddeder. İstemci değiştirirken
önce diğerindeki finance-rag bağlantısını durdur/devre dışı bırak. İki istemcinin
aynı anda aynı kütüphaneyi kullanması, ileride ortak bir sunucu bağlantısı gerektirir.

PDF dönüştürme ve embedding yerelde çalışır. Araçların döndürdüğü pasajlar,
yanıtı hazırlamak üzere seçtiğin sohbet sağlayıcısına iletilir.
Bağlantının çalışması, OCR kalitesinin doğrulandığı anlamına gelmez. Aktif motor,
ayrı Python ortamındaki Marker 1.10.1'dir; `llama-server` kurulmaz.
Gerçek model ağırlıkları ve PDF kabul testinin güncel durumu `verification.md` içindedir.

## Kaynaklar

- [OpenAI Docs: yerel MCP, masaüstü ayarları ve paylaşılan TOML](https://learn.chatgpt.com/docs/extend/mcp)
- [OpenAI Docs: hosted ChatGPT bağlantısı](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [MCP resmî rehberi: Claude Desktop yapılandırması](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
- [Claude resmî rehberi: yerel MCP ve masaüstü eklentileri](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)
