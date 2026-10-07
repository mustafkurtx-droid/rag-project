# Doğrulama kapsamı

## Otomatik testler

Gerçek Chroma persistence, SQLite FTS5/BM25, metadata/tarih filtresi, deduplication,
başarısız dönüşüm ve kısmi vektör yazımı sonrası temizleme, yeniden başlatma kurtarması,
tek süreç kilidi, kaynak sayfa parçalama ve gerçek FastMCP client/server arayüzü test edilir.
Marker ve E5 test çiftleri yalnızca test dosyalarında bulunur; üretimde sahte embedding yolu yoktur.

## Gerçek model kabul seti

İki sayfalık sentetik örnek `output/pdf/finance-risk-acceptance.pdf` dosyasında:
bir dijital risk sayfası ve gömülü metin içermeyen bir kredi riski taraması.
Gerçek modelleri ve ayrı stdio MCP sunucusunu kullanarak kontrol etmek için:

```powershell
.venv/Scripts/python.exe scripts/verify_real_pdf.py
```

Script `data/acceptance/inbox/finance-risk-acceptance.pdf` dosyasını ayrı
`data/acceptance/store` kütüphanesine ekler. Negatif ondalık tutarlar, OCR doğrulama
kelimesi, taranmış sayfadaki tutarlar, Türkçe anlamsal sorgu, karma/anahtar kelime
araması ve fiziksel sayfa atıflarını kontrol eder. Başarılı olduğunda sonuçları
`data/acceptance/acceptance-report.json` içine yazar. İlk koşum büyük model
indirmeleri gerektirir; güncel gerçek koşum sonucu `verification.md` içindedir.

Model indirmeleri için yeterli alanı olan bir disk gerekiyorsa `.env` içinde
`FINRAG_MODEL_CACHE_DIR=E:/finance-rag-cache` gibi bir yol ayarla. Marker modelleri
ve indirme geçici dosyaları, E5 model dosyaları bu klasörün altına yerleşir.
Model önbelleği indekslenen belgelerden ayrıdır; `FINRAG_DATA_DIR` değişmez.
Hugging Face Xet adresi ulaşılamıyorsa `FINRAG_EMBEDDING_DISABLE_XET=true`
standart HTTPS indirmesini seçer. Bu seçenek, yönlendirme hedefinin de ağ tarafından
engellendiği durumları çözmez. Ayar değişikliğinden sonra MCP bağlantısını yeniden başlat.

Her biri için PDF'i `data/inbox` altına koy, `finance-rag add` çalıştır ve `pdf_get_page`
çıktısıyla orijinal PDF'i karşılaştır:

| Örnek | Kabul ölçütü |
|---|---|
| Türkçe dijital TCMB benzeri rapor | Türkçe başlıklar, negatif işaretler, yüzde ve fiziksel sayfa doğru |
| İngilizce risk makalesi | Türkçe soruya ilgili İngilizce pasaj ilk 5 içinde |
| Taranmış PDF | OCR gerçekten çalışıyor; boş belge indekslenmiyor |
| VaR/ES matematik sayfası | Formül, güven düzeyi ve kayıp işaret konvansiyonu kaybolmuyor |
| Uzun finansal tablo | Başlık, dönem, birim ve dipnot tam sayfada doğrulanabiliyor |
| Benzer başlıklı eski/yeni rapor | `as_of` yeni raporu ve tarihsiz belgeyi dışlıyor |
| Konu dışı soru | İstemci, getirilen ilgisiz metinden kesin bir cevap üretmiyor |

En az 20 kendi sorun için beklenen belge/sayfayı elle etiketle. Recall@5, doğru sayfa
atıf oranı ve yanıtsız sorularda desteklenmeyen iddia sayısını ayrı ölç.
Bu projeyle hazır bir finans korpusu, güncel piyasa verisi veya ölçülmüş retrieval skoru verilmez.
