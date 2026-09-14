-- Kalıcı lakehouse ayarları (D04, ADR-0067). İlk kayıt: seri kataloğu kipi.
--   series_catalog = 'default' → bootstrap her açılışta Git'teki başlangıç kataloğunu (catalog/series/*.yml) yükler
--   series_catalog = 'none'    → şema kurulur, başlangıç kataloğu YÜKLENMEZ (boş katalogdan yeni alan)
-- Kip veritabanında durduğu için sonraki ingest/silver/gold/promote çağrıları ve yeniden açılış kararı değiştirmez.
CREATE TABLE IF NOT EXISTS meta.lakehouse_setting (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
