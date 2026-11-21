"""vakit_uret.py birim testleri (ağsız, uykusuz). Çalıştırma: python -m unittest discover -s veri -v"""

import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vakit_uret as vu  # noqa: E402

FIKSTUR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_fikstur")
IS_AKISI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".github", "workflows", "vakitler.yml")
# Fikstür günleri 09.11.2026..18.11.2026; bugün 10.11 alınınca son gün bugün+8.
BUGUN = date(2026, 11, 10)
SIMDI = datetime(2026, 11, 10, 6, 30, tzinfo=vu.TR)


def fikstur(ad):
    with open(os.path.join(FIKSTUR, ad), encoding="utf-8") as f:
        return json.load(f)


def gun(tarih, saatler=("06:11", "07:38", "12:54", "15:34", "17:59", "19:21")):
    return {"tarih": tarih, **dict(zip(vu.VAKITLER, saatler))}


def gunler(baslangic, sayi):
    return [gun(date.fromordinal(baslangic.toordinal() + i).isoformat()) for i in range(sayi)]


def vakit_verisi(gun_listesi):
    return {"surum": 1, "ilce_id": "9206", "ilce_adi": "ANKARA", "il_adi": "ANKARA", "kaynak": "emushaf",
            "zaman_dilimi": "Europe/Istanbul", "uretim": "2026-11-10T06:30:00+03:00", "gunler": gun_listesi}


class SahteIstemci:
    """URL -> fikstür yanıtı. 'bozuk' sözlüğündeki URL'ler için VeriHatasi ya da verilen yanıt döner."""

    def __init__(self, ozel=None):
        self.ozel = ozel or {}
        self.istekler = []

    def json_getir(self, url):
        self.istekler.append(url)
        if url in self.ozel:
            yanit = self.ozel[url]
            if isinstance(yanit, Exception):
                raise yanit
            return yanit
        yol = url.replace(vu.EmushafKaynak.ADRES, "")
        if yol == "/sehirler/2":
            return fikstur("sehirler.json")
        if yol.startswith("/ilceler/"):
            return fikstur(f"ilceler_{yol.split('/')[-1]}.json")
        if yol.startswith("/vakitler/"):
            return fikstur("vakitler_ornek.json")
        raise AssertionError(f"beklenmeyen URL {url}")


class GunCevirmeTesti(unittest.TestCase):
    def test_gunes_ve_aksam_tuzagi(self):
        ham = fikstur("vakitler_ornek.json")[0]
        # Fikstürde GunesDogus/GunesBatis farklı değerler: yanlış alan seçilirse test düşer.
        self.assertNotEqual(ham["Gunes"], ham["GunesDogus"])
        self.assertNotEqual(ham["Aksam"], ham["GunesBatis"])
        g = vu.gun_cevir(ham)
        self.assertEqual(g, {"tarih": "2026-11-09", "imsak": "06:11", "gunes": "07:38", "ogle": "12:54",
                             "ikindi": "15:34", "aksam": "17:59", "yatsi": "19:21"})

    def test_tarih_cevirme(self):
        ham = dict(fikstur("vakitler_ornek.json")[0], MiladiTarihKisa="01.03.2027")
        self.assertEqual(vu.gun_cevir(ham)["tarih"], "2027-03-01")
        for bozuk in ("2026-11-09", "31.02.2027", "", None):
            with self.subTest(bozuk=bozuk), self.assertRaises(vu.VeriHatasi):
                vu.gun_cevir(dict(ham, MiladiTarihKisa=bozuk))

    def test_eksik_alan(self):
        ham = dict(fikstur("vakitler_ornek.json")[0])
        del ham["Gunes"]
        with self.assertRaises(vu.VeriHatasi):
            vu.gun_cevir(ham)


class DogrulamaTesti(unittest.TestCase):
    def test_gecerli(self):
        vu.dogrula_vakit(vakit_verisi(gunler(date(2026, 11, 9), 10)), BUGUN)

    def test_artmayan_saat_reddi(self):
        for saatler in (("06:11", "07:38", "07:38", "15:34", "17:59", "19:21"),
                        ("06:11", "12:54", "07:38", "15:34", "17:59", "19:21")):
            g = gunler(date(2026, 11, 9), 10)
            g[3] = gun(g[3]["tarih"], saatler)
            with self.subTest(saatler=saatler), self.assertRaises(vu.VeriHatasi):
                vu.dogrula_vakit(vakit_verisi(g), BUGUN)

    def test_gecersiz_saat(self):
        for s in ("24:00", "7:38", "07:60", "07.38", "", 738):
            g = gunler(date(2026, 11, 9), 10)
            g[0] = dict(g[0], imsak=s)
            with self.subTest(s=s), self.assertRaises(vu.VeriHatasi):
                vu.dogrula_vakit(vakit_verisi(g), BUGUN)

    def test_tekrar_bosluk_ve_sira(self):
        temel = gunler(date(2026, 11, 9), 10)
        durumlar = {
            "tekrar": temel[:5] + [temel[4]] + temel[5:],
            "bosluk": temel[:4] + temel[5:],
            "ters": temel[:4] + [temel[5], temel[4]] + temel[6:],
        }
        for ad, g in durumlar.items():
            with self.subTest(ad), self.assertRaises(vu.VeriHatasi):
                vu.dogrula_vakit(vakit_verisi(g), BUGUN)

    def test_tarih_bicimi(self):
        for t in ("09.11.2026", "2026-02-30", "2026-1-09"):
            g = gunler(date(2026, 11, 9), 10)
            g[0] = dict(g[0], tarih=t)
            with self.subTest(t=t), self.assertRaises(vu.VeriHatasi):
                vu.dogrula_vakit(vakit_verisi(g), BUGUN)

    def test_anahtar_kumesi(self):
        g = gunler(date(2026, 11, 9), 10)
        fazla = [dict(g[0], gunes_dogus="07:45")] + g[1:]
        eksik = [{k: v for k, v in g[0].items() if k != "yatsi"}] + g[1:]
        for ad, liste in (("fazla", fazla), ("eksik", eksik)):
            with self.subTest(ad), self.assertRaises(vu.VeriHatasi):
                vu.dogrula_vakit(vakit_verisi(liste), BUGUN)

    def test_yedi_gun_ileri_sarti(self):
        vu.dogrula_vakit(vakit_verisi(gunler(date(2026, 11, 9), 9)), BUGUN)  # son 17.11 = bugün+7
        with self.assertRaises(vu.VeriHatasi):
            vu.dogrula_vakit(vakit_verisi(gunler(date(2026, 11, 9), 8)), BUGUN)  # son 16.11

    def test_ust_alanlar_dolu(self):
        for alan, deger in (("surum", 2), ("ilce_id", ""), ("kaynak", None), ("zaman_dilimi", " "),
                            ("uretim", ""), ("uretim", "dün"), ("gunler", [])):
            veri = vakit_verisi(gunler(date(2026, 11, 9), 10))
            veri[alan] = deger
            with self.subTest(alan=alan, deger=deger), self.assertRaises(vu.VeriHatasi):
                vu.dogrula_vakit(veri, BUGUN)

    def test_dizin(self):
        dizin = {"surum": 1, "kaynak": "emushaf", "uretim": "x",
                 "iller": [{"il_id": "506", "il_adi": "ANKARA", "ilceler": [{"ilce_id": "9206", "ilce_adi": "ANKARA"}]}]}
        vu.dogrula_dizin(dizin)
        tekrar = json.loads(json.dumps(dizin))
        tekrar["iller"].append({"il_id": "507", "il_adi": "X", "ilceler": [{"ilce_id": "9206", "ilce_adi": "Y"}]})
        bos = json.loads(json.dumps(dizin))
        bos["iller"][0]["ilceler"] = []
        for ad, veri in (("tekrar", tekrar), ("bos", bos)):
            with self.subTest(ad), self.assertRaises(vu.VeriHatasi):
                vu.dogrula_dizin(veri)


class BirlestirmeTesti(unittest.TestCase):
    def test_birlestirme(self):
        onceki = [gun("2026-11-07"), gun("2026-11-08"), gun("2026-11-09"),
                  gun("2026-11-10", ("01:00", "02:00", "03:00", "04:00", "05:00", "06:00")), gun("2026-11-20")]
        yeni = [gun("2026-11-10"), gun("2026-11-11")]
        sonuc = {g["tarih"]: g for g in vu.birlestir(onceki, yeni, BUGUN)}
        self.assertNotIn("2026-11-07", sonuc)  # bugün-3 budandı
        self.assertNotIn("2026-11-08", sonuc)  # bugün-2 budandı
        self.assertIn("2026-11-09", sonuc)  # bugün-1 korundu
        self.assertEqual(sonuc["2026-11-10"]["imsak"], "06:11")  # aynı tarihte yeni değer kazandı
        self.assertIn("2026-11-20", sonuc)  # yalnız öncekinde olan gelecek gün korundu
        self.assertEqual(list(sonuc), sorted(sonuc))


class IstemciTesti(unittest.TestCase):
    def _istemci(self, getir):
        saat = [100.0]
        bekleme = []

        def bekle(sn):
            bekleme.append(sn)
            saat[0] += sn

        return vu.NazikIstemci(getir=getir, bekle=bekle, saat=lambda: saat[0]), bekleme

    def test_yeniden_deneme_sonra_basari(self):
        cagri = []

        def getir(url):
            cagri.append(url)
            if len(cagri) < 3:
                raise OSError("bağlantı koptu")
            return b'[1]'

        istemci, bekleme = self._istemci(getir)
        self.assertEqual(istemci.json_getir("u"), [1])
        self.assertEqual(len(cagri), 3)
        self.assertEqual(bekleme, [1, 2])  # üstel bekleme; geri çekilme zaten >= 1 sn aralığı sağlar

    def test_en_cok_uc_yeniden_deneme(self):
        cagri = []

        def getir(url):
            cagri.append(url)
            return b'{bozuk'

        istemci, bekleme = self._istemci(getir)
        with self.assertRaises(vu.VeriHatasi):
            istemci.json_getir("u")
        self.assertEqual(len(cagri), 4)
        self.assertEqual(bekleme, [1, 2, 4])

    def test_istekler_arasi_en_az_bir_saniye(self):
        istemci, bekleme = self._istemci(lambda url: b'[]')
        istemci.json_getir("a")
        istemci.json_getir("b")
        self.assertEqual(bekleme, [1.0])

    def test_user_agent_ve_zaman_asimi(self):
        yakalanan = {}

        class Yanit:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                return b'[]'

        def sahte_urlopen(istek, timeout):
            yakalanan["ua"] = istek.get_header("User-agent")
            yakalanan["timeout"] = timeout
            return Yanit()

        with mock.patch.object(vu.urllib.request, "urlopen", sahte_urlopen):
            vu.ham_getir("https://ornek.invalid/x")
        self.assertEqual(yakalanan, {"ua": "EzanVaktiVeri/1.0", "timeout": 20})


class CalistirmaTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cikti = os.path.join(self.tmp.name, "cikti")

    def tearDown(self):
        self.tmp.cleanup()

    def _calistir(self, istemci, **kw):
        vu.calistir(vu.EmushafKaynak(istemci), self.cikti, simdi=SIMDI, kayit=lambda m: None, **kw)

    def test_basarili_uretim(self):
        istemci = SahteIstemci()
        self._calistir(istemci, ilce_idler=["9206", "9541"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.cikti, "vakitler"))), ["9206.json", "9541.json"])
        with open(os.path.join(self.cikti, "vakitler", "9541.json"), encoding="utf-8") as f:
            veri = json.load(f)
        vu.dogrula_vakit(veri, BUGUN)
        self.assertEqual((veri["ilce_id"], veri["ilce_adi"], veri["il_adi"]), ("9541", "İSTANBUL", "İSTANBUL"))
        self.assertEqual(veri["uretim"], "2026-11-10T06:30:00+03:00")
        self.assertEqual(veri["gunler"][0]["tarih"], "2026-11-09")  # 09.11 = bugün-1, korunur
        with open(os.path.join(self.cikti, "ilceler.json"), encoding="utf-8") as f:
            dizin = json.load(f)
        vu.dogrula_dizin(dizin)
        self.assertEqual([il["il_id"] for il in dizin["iller"]], ["506", "539"])
        self.assertNotIn("/vakitler/9205", " ".join(istemci.istekler))  # --ilce dışı ilçe istenmedi
        self.assertFalse([a for a in os.listdir(self.tmp.name) if a.startswith(".vakit_gecici_")])

    def test_onceki_yayinla_birlestirme(self):
        onceki = os.path.join(self.tmp.name, "onceki")
        os.makedirs(os.path.join(onceki, "vakitler"))
        # Önceki yayın fikstürle süreklidir (makullük: komşu gün/örtüşen gün farkı <= 5 dk): 08.11 = 09.11 değerleri,
        # 09.11-10.12 fikstür, 11-15.12 fikstürün son günü değerleriyle.
        fg = [vu.gun_cevir(h) for h in fikstur("vakitler_ornek.json")]
        saatler = lambda g: tuple(g[v] for v in vu.VAKITLER)  # noqa: E731
        son = date.fromisoformat(fg[-1]["tarih"])
        ek = [gun(date.fromordinal(son.toordinal() + i).isoformat(), saatler(fg[-1])) for i in range(1, 6)]
        eski = vakit_verisi([gun("2026-11-08", saatler(fg[0]))] + fg + ek)  # 15.12'ye kadar
        with open(os.path.join(onceki, "vakitler", "9206.json"), "w", encoding="utf-8") as f:
            json.dump(eski, f)
        self._calistir(SahteIstemci(), onceki=onceki, ilce_idler=["9206"])
        with open(os.path.join(self.cikti, "vakitler", "9206.json"), encoding="utf-8") as f:
            tarihler = [g["tarih"] for g in json.load(f)["gunler"]]
        self.assertEqual(tarihler[0], "2026-11-09")
        self.assertEqual(tarihler[-1], "2026-12-15")  # kaynakta olmayan 11-15.12 korundu

    def _kismi_basarisizlik(self, ozel):
        os.makedirs(self.cikti)
        nobetci = os.path.join(self.cikti, "nobetci.txt")
        with open(nobetci, "w", encoding="utf-8") as f:
            f.write("dokunma")
        istemci = SahteIstemci(ozel)
        kod = vu.main(["--cikti", self.cikti, "--ilce", "9206", "--ilce", "9541"], kaynak=vu.EmushafKaynak(istemci))
        self.assertEqual(kod, 1)
        # 9206 geçti, hata 9541'de (ikinci ilçe) çıktı: gerçekten "kısmi" başarısızlık.
        self.assertEqual(istemci.istekler[-2:], [f"{vu.EmushafKaynak.ADRES}/vakitler/{i}" for i in ("9206", "9541")])
        self.assertEqual(os.listdir(self.cikti), ["nobetci.txt"])
        with open(nobetci, encoding="utf-8") as f:
            self.assertEqual(f.read(), "dokunma")
        self.assertFalse([a for a in os.listdir(self.tmp.name) if a.startswith(".vakit_gecici_")])

    def test_kismi_basarisizlik_ag(self):
        with mock.patch.object(vu, "datetime", wraps=datetime) as dt:
            dt.now.return_value = SIMDI
            self._kismi_basarisizlik({f"{vu.EmushafKaynak.ADRES}/vakitler/9541": vu.VeriHatasi("ağ")})

    def test_kismi_basarisizlik_bozuk_veri(self):
        bozuk = fikstur("vakitler_ornek.json")
        bozuk[2] = dict(bozuk[2], Ogle=bozuk[2]["Gunes"])  # artmayan saat
        with mock.patch.object(vu, "datetime", wraps=datetime) as dt:
            dt.now.return_value = SIMDI
            self._kismi_basarisizlik({f"{vu.EmushafKaynak.ADRES}/vakitler/9541": bozuk})

    def test_dizinde_olmayan_ilce(self):
        with self.assertRaises(vu.VeriHatasi):
            self._calistir(SahteIstemci(), ilce_idler=["1"])
        self.assertFalse(os.path.exists(self.cikti))

    def test_dizin_yalniz(self):
        istemci = SahteIstemci()
        self._calistir(istemci, dizin_yalniz=True)
        self.assertTrue(os.path.exists(os.path.join(self.cikti, "ilceler.json")))
        self.assertEqual(os.listdir(os.path.join(self.cikti, "vakitler")), [])
        self.assertFalse([u for u in istemci.istekler if "/vakitler/" in u])


class IsAkisiYapiTesti(unittest.TestCase):
    """GERÇEK YAML ayrıştırması DEĞİLDİR (makinede ayrıştırıcı yok); yalnız stdlib metin denetimi."""

    @classmethod
    def setUpClass(cls):
        with open(IS_AKISI, encoding="utf-8") as f:
            cls.metin = f.read()
        cls.satirlar = cls.metin.splitlines()

    def _bolum(self, anahtar):
        i = self.satirlar.index(f"{anahtar}:")
        govde = []
        for s in self.satirlar[i + 1:]:
            if s and not s.startswith(" "):
                break
            govde.append(s)
        return govde

    def test_sekme_yok_ve_girinti_ikiser(self):
        self.assertNotIn("\t", self.metin)
        for s in self.satirlar:
            self.assertEqual((len(s) - len(s.lstrip(" "))) % 2, 0, s)

    def test_ust_anahtarlar(self):
        ust = [s.split(":")[0] for s in self.satirlar if s and not s.startswith((" ", "#"))]
        self.assertEqual(ust, ["name", "on", "permissions", "concurrency", "jobs"])

    def test_tetikleyiciler(self):
        on = self._bolum("on")
        self.assertIn("  schedule:", on)
        self.assertIn("  workflow_dispatch:", on)
        cron = [s for s in on if "cron:" in s]
        self.assertEqual(len(cron), 1)
        self.assertRegex(cron[0], r"cron: '\S+ \S+ \S+ \S+ \S+'")

    def test_izinler_ve_sirlar(self):
        self.assertEqual([s.strip() for s in self._bolum("permissions") if s.strip()], ["contents: write"])
        self.assertNotIn("secrets.", self.metin)
        self.assertIn("gh-pages", self.metin)
        self.assertIn("cancel-in-progress: false", self.metin)

    def test_action_surumleri(self):
        for s in self.satirlar:
            if "uses:" in s:
                self.assertRegex(s.strip(), r"^- uses: [\w.-]+/[\w.-]+@v\d+$|^uses: [\w.-]+/[\w.-]+@v\d+$")


if __name__ == "__main__":
    unittest.main()
