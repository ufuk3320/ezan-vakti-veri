"""Ezan Vakti veri betiği: kaynaktan ilçe başına vakit JSON'u üretir, doğrular, yazar.

Kullanım:
  python veri/vakit_uret.py --cikti <klasör> [--onceki <klasör>] [--ilce 9206 --ilce ...] [--dizin-yalniz]

Çıktı: <cikti>/ilceler.json ve <cikti>/vakitler/<ilce_id>.json.
Herhangi bir hata olursa sıfırdan farklı kodla çıkar ve <cikti>'ya hiçbir şey yazmaz.
Yalnız standart kütüphane.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

SURUM = 1
ZAMAN_DILIMI = "Europe/Istanbul"
# Türkiye 2016'dan beri yaz saati uygulamadan sabit UTC+3. (Windows'ta zoneinfo verisi yok.)
# Kural değişirse dokunulacak tek satır budur.
TR = timezone(timedelta(hours=3))

TURKIYE_ULKE_ID = "2"
VAKITLER = ("imsak", "gunes", "ogle", "ikindi", "aksam", "yatsi")
ILERI_GUN = 7  # budamadan sonra bugünden en az bu kadar gün ileri veri şart
# Kaynağın YENİ yanıtı tek başına bugünden en az bu kadar ileri gitmeli; önceki yayının tamponu
# kısa/boş/bayat yanıtı gizleyip yeni "uretim" damgasıyla yeniden yayınlanmasın.
YENI_ILERI_GUN = 14

ZAMAN_ASIMI = 20
ISTEK_ARALIGI = 1.0
YENIDEN_DENEME = 3  # toplam 1 + 3 deneme
USER_AGENT = "EzanVaktiVeri/1.0"
AZAMI_YANIT = 5 * 1024 * 1024  # bayt; aşan yanıt reddedilir

# Makullük sınırları (zehirli/kaymış kaynak verisine karşı; aşılırsa yayın yapılmaz)
AZAMI_GUNLUK_FARK = 5  # dk: ardışık iki günde aynı vakit
AZAMI_REVIZYON_FARK = 5  # dk: önceki yayınla aynı gün aynı vakit
OGLE_BANDI = ("11:00", "14:30")  # Türkiye için geniş bant
EN_AZ_IL = 81  # tam çalışmada dizindeki il sayısı

# fullmatch + [0-9]: sondaki "\n" ve Unicode rakamlar kabul edilmez
SAAT_RE = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
TARIH_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
KIMLIK_RE = re.compile(r"[0-9]{1,8}")


class VeriHatasi(Exception):
    pass


def kimlik_dogrula(deger, ad="kimlik"):
    """il/ilçe kimliği yalnız 1-8 ASCII rakam (URL'ye ve dosya yoluna girer)."""
    if not isinstance(deger, str) or not KIMLIK_RE.fullmatch(deger):
        raise VeriHatasi(f"geçersiz {ad}: {deger!r}")
    return deger


class YalnizHttpsYonlendirme(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise VeriHatasi(f"https dışı yönlendirme reddedildi: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


urllib.request.install_opener(urllib.request.build_opener(YalnizHttpsYonlendirme))


def ham_getir(url):
    istek = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(istek, timeout=ZAMAN_ASIMI) as yanit:
        veri = yanit.read(AZAMI_YANIT + 1)
    if len(veri) > AZAMI_YANIT:
        raise VeriHatasi(f"{url}: yanıt {AZAMI_YANIT} baytı aşıyor")
    return veri


class NazikIstemci:
    """İstekler arası >= 1 sn, en çok 3 yeniden deneme (1, 2, 4 sn üstel bekleme).
    getir/bekle/saat enjekte edilebilir (testler ağsız ve uykusuz koşar)."""

    def __init__(self, getir=ham_getir, bekle=time.sleep, saat=time.monotonic):
        self.getir = getir
        self.bekle = bekle
        self.saat = saat
        self.son_istek = None

    def json_getir(self, url):
        son_hata = None
        for deneme in range(YENIDEN_DENEME + 1):
            if deneme > 0:
                self.bekle(2 ** (deneme - 1))
            if self.son_istek is not None:
                gecen = self.saat() - self.son_istek
                if gecen < ISTEK_ARALIGI:
                    self.bekle(ISTEK_ARALIGI - gecen)
            self.son_istek = self.saat()
            try:
                return json.loads(self.getir(url))
            except (OSError, ValueError) as hata:  # ağ/HTTP/zaman aşımı/bozuk JSON
                son_hata = hata
        raise VeriHatasi(f"{url}: {YENIDEN_DENEME + 1} denemede alınamadı: {son_hata}")


def gun_cevir(ham):
    """emushaf gün kaydı -> şema günü. TUZAK: 'Gunes' (GunesDogus değil) ve 'Aksam' (GunesBatis değil)."""
    try:
        tarih = datetime.strptime(ham["MiladiTarihKisa"], "%d.%m.%Y").date().isoformat()
        return {
            "tarih": tarih,
            "imsak": ham["Imsak"],
            "gunes": ham["Gunes"],
            "ogle": ham["Ogle"],
            "ikindi": ham["Ikindi"],
            "aksam": ham["Aksam"],
            "yatsi": ham["Yatsi"],
        }
    except (KeyError, TypeError, ValueError) as hata:
        raise VeriHatasi(f"kaynak gün kaydı okunamadı: {hata!r}")


class EmushafKaynak:
    """Kaynak katmanı sınırı. Başka bir kaynak (ör. Awqat) aynı üç yöntemi ve 'ad' alanını
    sağlayan ayrı bir sınıf olarak eklenir; betiğin geri kalanı değişmez."""

    ad = "emushaf"
    ADRES = "https://ezanvakti.emushaf.net"

    def __init__(self, istemci):
        self.istemci = istemci

    def _liste(self, yol):
        yanit = self.istemci.json_getir(f"{self.ADRES}/{yol}")
        if not isinstance(yanit, list):
            raise VeriHatasi(f"{yol}: yanıt liste değil ({type(yanit).__name__})")
        return yanit

    def _ciftler(self, yol, kimlik_alani, ad_alani):
        try:
            return [(kimlik_dogrula(k[kimlik_alani], kimlik_alani), k[ad_alani]) for k in self._liste(yol)]
        except (KeyError, TypeError) as hata:
            raise VeriHatasi(f"{yol}: kayıt okunamadı: {hata!r}")

    def iller(self):
        return self._ciftler(f"sehirler/{TURKIYE_ULKE_ID}", "SehirID", "SehirAdi")

    def ilceler(self, il_id):
        return self._ciftler(f"ilceler/{kimlik_dogrula(il_id, 'il_id')}", "IlceID", "IlceAdi")

    def vakitler(self, ilce_id):
        return [gun_cevir(g) for g in self._liste(f"vakitler/{kimlik_dogrula(ilce_id, 'ilce_id')}")]


def _dolu_metin(deger):
    return isinstance(deger, str) and deger.strip() != ""


def dogrula_vakit(veri, bugun):
    """vakitler/<ilce_id>.json şemasını doğrular; bozuksa VeriHatasi."""
    if not isinstance(veri, dict) or veri.get("surum") != SURUM:
        raise VeriHatasi("surum eksik/yanlış")
    for alan in ("ilce_id", "kaynak", "zaman_dilimi", "uretim"):
        if not _dolu_metin(veri.get(alan)):
            raise VeriHatasi(f"{alan} boş")
    kimlik_dogrula(veri["ilce_id"], "ilce_id")
    try:
        datetime.fromisoformat(veri["uretim"])
    except ValueError:
        raise VeriHatasi("uretim ISO değil")
    gunler = veri.get("gunler")
    if not isinstance(gunler, list) or not gunler:
        raise VeriHatasi("gunler boş")
    onceki = None
    for gun in gunler:
        if not isinstance(gun, dict) or set(gun) != {"tarih", *VAKITLER}:
            raise VeriHatasi(f"gün anahtarları yanlış: {gun!r}")
        tarih_metni = gun["tarih"]
        if not isinstance(tarih_metni, str) or not TARIH_RE.fullmatch(tarih_metni):
            raise VeriHatasi(f"tarih biçimi yanlış: {tarih_metni!r}")
        try:
            tarih = date.fromisoformat(tarih_metni)
        except ValueError:
            raise VeriHatasi(f"geçersiz tarih: {tarih_metni!r}")
        if onceki is not None and tarih != onceki + timedelta(days=1):
            raise VeriHatasi(f"tarihler ardışık değil: {onceki} -> {tarih}")
        onceki = tarih
        saatler = [gun[v] for v in VAKITLER]
        for s in saatler:
            if not isinstance(s, str) or not SAAT_RE.fullmatch(s):
                raise VeriHatasi(f"{tarih_metni}: geçersiz saat {s!r}")
        if any(a >= b for a, b in zip(saatler, saatler[1:])):  # HH:MM metin sırası = zaman sırası
            raise VeriHatasi(f"{tarih_metni}: vakitler artan değil {saatler}")
    if onceki < bugun + timedelta(days=ILERI_GUN):
        raise VeriHatasi(f"son gün {onceki}: bugünden ({bugun}) en az {ILERI_GUN} gün ileri veri yok")


def dogrula_dizin(veri):
    """ilceler.json şemasını doğrular; bozuksa VeriHatasi."""
    if not isinstance(veri, dict) or veri.get("surum") != SURUM:
        raise VeriHatasi("dizin surum eksik/yanlış")
    for alan in ("kaynak", "uretim"):
        if not _dolu_metin(veri.get(alan)):
            raise VeriHatasi(f"dizin {alan} boş")
    iller = veri.get("iller")
    if not isinstance(iller, list) or not iller:
        raise VeriHatasi("dizin iller boş")
    gorulen = set()
    for il in iller:
        if not isinstance(il, dict) or not _dolu_metin(il.get("il_id")) or not _dolu_metin(il.get("il_adi")):
            raise VeriHatasi(f"il kaydı eksik: {il!r}")
        kimlik_dogrula(il["il_id"], "il_id")
        if not isinstance(il.get("ilceler"), list) or not il["ilceler"]:
            raise VeriHatasi(f"{il['il_adi']}: ilçe listesi boş")
        for ilce in il["ilceler"]:
            if not isinstance(ilce, dict) or not _dolu_metin(ilce.get("ilce_id")) or not _dolu_metin(ilce.get("ilce_adi")):
                raise VeriHatasi(f"ilçe kaydı eksik: {ilce!r}")
            kimlik_dogrula(ilce["ilce_id"], "ilce_id")
            if ilce["ilce_id"] in gorulen:
                raise VeriHatasi(f"ilçe kimliği tekrar: {ilce['ilce_id']}")
            gorulen.add(ilce["ilce_id"])


def birlestir(onceki_gunler, yeni_gunler, bugun):
    """Aynı tarihte yeni kazanır; yalnız öncekinde olan günler korunur; bugün-1'den eski günler budanır."""
    gunler = {g["tarih"]: g for g in onceki_gunler}
    gunler.update({g["tarih"]: g for g in yeni_gunler})
    sinir = (bugun - timedelta(days=1)).isoformat()
    return [gunler[t] for t in sorted(gunler) if t >= sinir]


def _dakika(saat):
    if not isinstance(saat, str) or not SAAT_RE.fullmatch(saat):
        raise VeriHatasi(f"geçersiz saat {saat!r}")
    return int(saat[:2]) * 60 + int(saat[3:])


def makullik_denetle(gunler, onceki_gunler, yeni_gunler):
    """Şemadan geçmiş veride zehirli/kaymış saat arar (fail-closed). Şema doğrulamasından SONRA çağrılır."""
    for dun, bugun_ in zip(gunler, gunler[1:]):
        for v in VAKITLER:
            if abs(_dakika(bugun_[v]) - _dakika(dun[v])) > AZAMI_GUNLUK_FARK:
                raise VeriHatasi(f"{dun['tarih']}->{bugun_['tarih']} {v}: {dun[v]}->{bugun_[v]} "
                                 f"günlük fark {AZAMI_GUNLUK_FARK} dk'yı aşıyor")
    eski = {g["tarih"]: g for g in onceki_gunler}
    kalan = {g["tarih"] for g in gunler}  # budanan (doğrulanmamış) günler karşılaştırılmaz
    for g in yeni_gunler:
        if g["tarih"] in eski and g["tarih"] in kalan:
            for v in VAKITLER:
                if abs(_dakika(g[v]) - _dakika(eski[g["tarih"]][v])) > AZAMI_REVIZYON_FARK:
                    raise VeriHatasi(f"{g['tarih']} {v}: önceki yayın {eski[g['tarih']][v]}, yeni {g[v]}; "
                                     f"fark {AZAMI_REVIZYON_FARK} dk'yı aşıyor")
    for g in gunler:
        if not OGLE_BANDI[0] <= g["ogle"] <= OGLE_BANDI[1]:
            raise VeriHatasi(f"{g['tarih']}: öğle {g['ogle']} makul bant {OGLE_BANDI} dışında")


def _json_oku(yol):
    with open(yol, encoding="utf-8") as f:
        return json.load(f)


def _json_yaz(yol, veri):
    with open(yol, "w", encoding="utf-8", newline="\n") as f:
        json.dump(veri, f, ensure_ascii=False, separators=(",", ":"))


def onceki_gunleri_oku(onceki_klasor, ilce_id):
    """Önceki yayındaki günler; dosya yoksa (ilk çalışma/yeni ilçe) boş. Dosya bozuksa hata (sessizce düşürülmez)."""
    if not onceki_klasor:
        return []
    kimlik_dogrula(ilce_id, "ilce_id")
    yol = os.path.join(onceki_klasor, "vakitler", f"{ilce_id}.json")
    if not os.path.exists(yol):
        return []
    try:
        veri = _json_oku(yol)
    except (OSError, ValueError) as hata:
        raise VeriHatasi(f"önceki yayın okunamadı ({ilce_id}): {hata}")
    if not isinstance(veri, dict) or veri.get("ilce_id") != ilce_id or not isinstance(veri.get("gunler"), list):
        raise VeriHatasi(f"önceki yayın bozuk ({ilce_id})")
    for g in veri["gunler"]:
        if not isinstance(g, dict) or not isinstance(g.get("tarih"), str):
            raise VeriHatasi(f"önceki yayında bozuk gün ({ilce_id}): {g!r}")
    return veri["gunler"]


def calistir(kaynak, cikti, onceki=None, ilce_idler=None, dizin_yalniz=False, simdi=None, kayit=print):
    """Tümünü geçici klasörde üretip doğrular; ancak hepsi geçerse dosyaları <cikti>'ya taşır."""
    simdi = (simdi or datetime.now(TR)).astimezone(TR)
    bugun = simdi.date()
    uretim = simdi.replace(microsecond=0).isoformat()

    iller = []
    ilce_bilgisi = {}
    for il_id, il_adi in kaynak.iller():
        ilceler = []
        for ilce_id, ilce_adi in kaynak.ilceler(il_id):
            ilceler.append({"ilce_id": ilce_id, "ilce_adi": ilce_adi})
            ilce_bilgisi[ilce_id] = (ilce_adi, il_adi)
        iller.append({"il_id": il_id, "il_adi": il_adi, "ilceler": ilceler})
    dizin = {"surum": SURUM, "kaynak": kaynak.ad, "uretim": uretim, "iller": iller}
    dogrula_dizin(dizin)
    if not ilce_idler and not dizin_yalniz and len(iller) < EN_AZ_IL:
        raise VeriHatasi(f"dizinde {len(iller)} il var; tam çalışmada en az {EN_AZ_IL} beklenir")
    kayit(f"dizin: {len(iller)} il, {len(ilce_bilgisi)} ilçe")

    if dizin_yalniz:
        hedefler = []
    elif ilce_idler:
        for i in ilce_idler:
            kimlik_dogrula(i, "--ilce")
        bilinmeyen = [i for i in ilce_idler if i not in ilce_bilgisi]
        if bilinmeyen:
            raise VeriHatasi(f"dizinde olmayan ilçe: {bilinmeyen}")
        hedefler = list(dict.fromkeys(ilce_idler))
    else:
        hedefler = list(ilce_bilgisi)

    dosyalar = []  # (göreli yol, veri)
    for sira, ilce_id in enumerate(hedefler, 1):
        ilce_adi, il_adi = ilce_bilgisi[ilce_id]
        try:
            onceki_gunler = onceki_gunleri_oku(onceki, ilce_id)
            yeni_gunler = kaynak.vakitler(ilce_id)
            yeni_son = max((g["tarih"] for g in yeni_gunler), default=None)
            if yeni_son is None or yeni_son < (bugun + timedelta(days=YENI_ILERI_GUN)).isoformat():
                raise VeriHatasi(f"kaynak yanıtının son günü {yeni_son}; bugünden ({bugun}) en az "
                                 f"{YENI_ILERI_GUN} gün ileri gerekir (önceki yayın tamponu sayılmaz)")
            gunler = birlestir(onceki_gunler, yeni_gunler, bugun)
            veri = {
                "surum": SURUM, "ilce_id": ilce_id, "ilce_adi": ilce_adi, "il_adi": il_adi,
                "kaynak": kaynak.ad, "zaman_dilimi": ZAMAN_DILIMI, "uretim": uretim, "gunler": gunler,
            }
            dogrula_vakit(veri, bugun)
            makullik_denetle(gunler, onceki_gunler, yeni_gunler)
        except VeriHatasi as hata:
            raise VeriHatasi(f"ilçe {ilce_id} ({ilce_adi}): {hata}")
        dosyalar.append((os.path.join("vakitler", f"{ilce_id}.json"), veri))
        kayit(f"[{sira}/{len(hedefler)}] {ilce_id} {il_adi}/{ilce_adi}: {gunler[0]['tarih']}..{gunler[-1]['tarih']}")
    dosyalar.append(("ilceler.json", dizin))

    cikti = os.path.abspath(cikti)
    ust = os.path.dirname(cikti)
    os.makedirs(ust, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ust, prefix=".vakit_gecici_") as gecici:  # aynı birim: os.replace atomik
        os.makedirs(os.path.join(gecici, "vakitler"))
        kok = os.path.realpath(gecici)
        for goreli, veri in dosyalar:
            hedef = os.path.realpath(os.path.join(gecici, goreli))
            if os.path.commonpath([kok, hedef]) != kok or os.path.dirname(hedef) not in (kok, os.path.join(kok, "vakitler")):
                raise VeriHatasi(f"yazma yolu geçici klasör dışında: {goreli!r}")
            _json_yaz(hedef, veri)
        # Yazılanı geri okuyup yeniden doğrula (diske giden bayt doğru mu).
        for goreli, _ in dosyalar:
            okunan = _json_oku(os.path.join(gecici, goreli))
            if goreli == "ilceler.json":
                dogrula_dizin(okunan)
            else:
                dogrula_vakit(okunan, bugun)
        os.makedirs(os.path.join(cikti, "vakitler"), exist_ok=True)
        for goreli, _ in dosyalar:
            os.replace(os.path.join(gecici, goreli), os.path.join(cikti, goreli))
    kayit(f"yazıldı: {cikti} ({len(dosyalar) - 1} ilçe + ilceler.json)")


def main(argv=None, kaynak=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ayr = argparse.ArgumentParser(description="Ezan vakti verisi üretir.")
    ayr.add_argument("--cikti", required=True, help="çıktı klasörü")
    ayr.add_argument("--onceki", help="önceki yayın klasörü (birleştirme için)")
    ayr.add_argument("--ilce", action="append", help="yalnız bu ilçe kimlikleri (tekrarlanabilir)")
    ayr.add_argument("--dizin-yalniz", action="store_true", help="yalnız ilceler.json üret")
    arg = ayr.parse_args(argv)
    kaynak = kaynak or EmushafKaynak(NazikIstemci())
    try:
        calistir(kaynak, arg.cikti, onceki=arg.onceki, ilce_idler=arg.ilce, dizin_yalniz=arg.dizin_yalniz)
    except (VeriHatasi, OSError) as hata:
        print(f"HATA: {hata} -- çıktı klasörüne hiçbir şey yazılmadı.", file=sys.stderr)
        return 1
    except Exception as hata:  # beklenmeyen hata da fail-closed: yazma yalnız en sonda, buraya gelmeden
        print(f"HATA (beklenmeyen): {hata!r} -- çıktı klasörüne hiçbir şey yazılmadı.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
