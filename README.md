# vigilant-happiness (versi sedot WC)

Scrape Google Maps -> leads sedot WC (tanpa website, ada nomor HP, rating bagus, aktif).

Cara pakai: Actions -> Scrape Gmaps -> Run workflow.
- min_rating (default 4.5), max_days (default 180), extra_reviews (default true, perlu untuk filter aktif).
- Hasil: leads.csv di Artifacts, urut: tanpa web -> ulasan terakhir paling baru -> ulasan terbanyak.
- contacted.txt (opsional): nomor yang sudah dihubungi, satu per baris, otomatis dibuang.
