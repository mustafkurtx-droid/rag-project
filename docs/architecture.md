# Mimari kararları

## 1. Sınır: araştırma bilgisi katmanı

Bu proje kişisel finans/risk/ekonomi bilgi tabanıdır. PDF'lerden bulunan yöntem,
tanım, bulgu ve varsayımlar MCP istemcisindeki modele kanıt olarak döner.
BIST risk tahmini veya şirket kârlılığı regresyonu gibi analiz projeleri bu bilgi
katmanını kullanabilir. VaR hesaplamak, regresyon tahmin etmek veya piyasa verisi
indirmek ayrı araçların sorumluluğudur; burada kaynak metninden rakam uydurulmaz.

## 2. İki repo, tek uygulama

pdfrag'in `server / database / embeddings / chunking / pdf` ayrımı ve PDF yönetimi
araçları referans alındı. Uygulama `finance_rag` adı altında yeniden yazıldı.
Marker'ın kapsamlı OCR kodu kopyalanmadı: kendi `PdfConverter`, `create_model_dict`
ve `save_output` API'leri kullanılıyor. Kullanıcının sunucu kurmama tercihiyle
aktif sürüm Marker 1.10.1 olarak sabitlendi. `.marker-venv` içinde yerel Surya/PyTorch
OCR kullanılır; indirilen Marker 2 deposu referans olarak korunur.
Marker worker dışında PDF okuyan ikinci bir üretim yolu bulunmaz.

## 3. Dönüşüm ve kaynak bütünlüğü

- İzin verilen dizin, uzantı, PDF imzası ve boyut kontrol edilir.
- PDF önce sabit bir kopyaya alınır; SHA-256 bu kopyayla aynı byte akışından hesaplanır.
- Aynı içerik başka adla eklense de tek belge sayılır. İlk metadata korunur.
- Marker ayrı süreçte çalışır; stdout/stderr `marker.log` dosyasına gider.
- `paginate_output=True`; Marker'ın `{0}------------------------------------------------`
  sınırı **fiziksel PDF sayfa 1** olarak kaydedilir. Basılı Roma rakamlı sayfalarla karıştırılmaz.
- Sınır eksikse, sıra bozuksa veya page_stats çelişiyorsa belge indekslenmez.
- Tam Markdown, görseller, orijinal PDF kopyası, sayfalar ve Marker metadata diskte korunur.
- Temizlikte ondalık virgül/nokta, negatif işaret, para birimi, yüzde ve LaTeX yeniden yazılmaz.
  Marker/OCR hatasızlık garantisi vermez; sayısal analizden önce kaynak sayfa doğrulanır.

Worker model oluşturmadan önce Marker sürümünü doğrular; Marker 2 reddedilir.
Marker 1.10.1 modelleri Python işçi sürecinde yükler; harici inference daemon yoktur.
`force_ocr` desteği korunur, `use_llm=False` kalır. Worker sona erdiğinde modellerin
ömrü de biter. Eski Surya sunucu ortam değişkenleri işçiye aktarılmaz.

## 4. Parçalama ve embedding

Parçalar sayfalar arasında geçmez; hiyerarşik bölüm başlığı sonraki sayfaya taşınabilir.
Metin paragrafları token bütçesine kadar birleşir. Tablo, kod ve blok formülü ayrı tutulur.
Büyük tablolarda başlık ve ayraç satırı her parçada tekrar edilir. Tek satır veya formül
model sınırını aşarsa metin bölünür ve `fragmented=true` işaretlenir; tam sayfaya dönülür.
Sayfalar arası tablolar otomatik birleştirilmez. HTML tabloları ve çok karmaşık tablolar
özel yapısal ayrıştırma garantisi kapsamında değildir.

Varsayılan `intfloat/multilingual-e5-base`, Türkçe/İngilizce araştırma için seçildi.
Girdi `query: ...` veya `passage: ...` öneki alır, vektörler normalize edilir.
Gerçek model tokenizer'ı parça bütçesini ölçer; başlık ve önek bütçeye dahildir.
Varsayılan 384 token; embedding katmanı 512/model limitini aşan girdiyi sessizce
kırpmak yerine reddeder. Çok uzun sorgu kısaltılmalıdır.
Model değişikliği aynı indekste reddedilir; yeni veri dizininde PDF'ler yeniden eklenir.
Bu sürüm model ismini kaydeder; model deposunun immutable revision pin'i henüz yoktur.

## 5. Katalog, hibrit arama ve tarih

Chroma tek vektör deposudur ve cosine mesafesi kullanır. SQLite şunları tutar:

- Belge kataloğu, metadata ve hazır/indeksleniyor/siliniyor durumu.
- Kaynak parçaları ve FTS5 BM25 indeksi.
- Kalıcı PDF iş kayıtları.

Hibrit arama, orijinal sorgunun anlamsal sonuçlarını ve sınırlı finans terimi
eşlemeleriyle genişletilen sözcüksel sonuçları Reciprocal Rank Fusion ile birleştirir.
`1 / (60 + rank)` katkıları toplanır. Bu skor olasılık veya doğruluk yüzdesi değildir.
İki kol da **aynı metadata filtrelerini** uygular. Kurum/coğrafya/risk türü filtreleri
tam eşleşmedir; metadata yazarken aynı isimlendirmeyi kullan. `tags` bu sürümde
katalog bilgisidir, arama filtresi değildir. Reranker ve relevance threshold henüz yoktur;
en yakın sonuçlar soruya gerçekten yanıt vermeyebilir.

`as_of` kullanıcı tarafından verilen yayın tarihine dayanır; tarihsiz ve ileri
tarihli belgeler dışarıda kalır. Rapor dönemi, veri gözlem tarihi ve ilk yayımlanma
tarihi aynı şey değildir. Backtest için point-in-time veri erişilebilirliği ayrıca kurulmalıdır.

## 6. İşler ve hata davranışı

`pdf_add` işi SQLite'a kaydedip tek işçili sıraya alır. Kuyruk sınırı vardır.
`pdf_job_status`: queued → running → succeeded/failed. Sunucu yeniden başladığında
tamamlanmamış işler interrupted olur ve istemci yeniden gönderebilir.
İşin kuyruğa alınması dosya snapshot'ı alındığı anlamına gelmez; dosya okunana kadar
giriş PDF'ini yerinde tut. Aynı dosya ikinci kez sıraya alınırsa işçi içerik hash'iyle tekilleştirir.

İndeksleme vektörleri tamamlamadan belge görünür olmaz. SQLite yayınlama işlemi
transaction kullanır. Hatalarda iki indeks temizlenir; uygulama çökmesi halinde
indeksleniyor/siliniyor kayıtları sonraki açılışta temizlenir. İki veri deposunu kapsayan
dağıtık transaction yoktur; durum kayıtları ve yeniden başlatma temizliği kullanılır.
Tek süreç kilidi ikinci sunucu/CLI yazıcısını engeller. Süreç içi kilitler okuma-yazmayı
senkronize eder; büyük embedding sorguları sırasında diğer indeks işlemleri bekleyebilir.
Kişisel yerel kullanım için tasarlandı, yüksek eşzamanlılık hedeflenmedi.

`pdf_remove` arama indekslerini kaldırır, dönüşüm eserlerini ve kaynak kopyasını tutar.
Başarısız işler log/eser bırakabilir. Diskten tam silme bu aracın kapsamı değildir.
CLI aynı veri dizininde sunucuyla eşzamanlı çalışmaz. Yedek için sunucuyu kapatıp
`data` klasörünün tamamını kopyala; yalnızca Chroma klasörünü almak yeterli değildir.

## 7. MCP sözleşmesi

FastMCP lifespan uygulamayı açar/kapatır. Ağır işlemler event loop dışında çalışır.
MCP araçları JSON şemalarıyla doğrulanır; liste ve sayfa araçları sayfalıdır.
Sunucu yalnızca stdio sunar. HTTP/auth/uzak yayın bu sürüme dahil değildir.
Salt okuma ve silme araçlarının MCP annotation bilgileri tanımlıdır.

Kanıt cevabı: `document_id`, `id` (chunk), `filename`, `title`, `page`, `section`,
`text`, `kind`, `fragmented`, `publication_date`, `source_url`, `citation`, sıralama skorları.
PDF içindeki talimatlar güvenilmeyen kaynak metni olarak ele alınır. Kaynak/prompt
kuralları bu davranışı istemci modele bildirir; model davranışını zorlayan bir güvenlik
sınırı veya kaynak doğrulama sistemi değildir.

## 8. Doğal genişletmeler

Önce kendi PDF kümenle sayfa doğruluğu ve retrieval recall ölçülmeli. Sonra gerekirse:

1. Finans sorularından etiketli değerlendirme seti ve recall@k ölçümü.
2. Çok dilli cross-encoder reranker; belge çeşitliliği ve alaka eşiği.
3. Tablo yapısını JSON olarak veren ikinci Marker renderer ve birim/dönem şemaları.
4. Ayrı finans hesaplama MCP'si: veri versiyonu belirli VaR/ES/backtest fonksiyonları.
5. Kurum raporu izleme/indirme; metadata ve kaynak tarihini otomatik doğrulama.
