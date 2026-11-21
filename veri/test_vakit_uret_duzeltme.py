"""3.1 Aşama 05 düzeltmeleri için ek testler (A yol geçişi, B ağ sertleştirme, C makullük).
Çalıştırma: python -m unittest discover -s veri -v"""

import json
import os
import sys
import tempfile
import unittest
import urllib.request
from datetime import date, datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_vakit_uret as tv  # noqa: E402
import vakit_uret as vu  # noqa: E402
from test_vakit_uret_uc import CiktiDokunulmamisTabani  # noqa: E402

ADRES = vu.EmushafKaynak.ADRES
KOTU_KIMLIKLER = ("../x", "/abs", "9206/../x", "", "..\\x", "C:\\x", "٩٢٠٦", "123456789", "9206\n", " 9206")


def fikstur_gunleri():
    return [vu.gun_cevir(g) for g in tv.fikstur("vakitler_ornek.json")]


class YolGecisiTesti(CiktiDokunulmamisTabani):
    def test_kimlik_dogrula(self):
        self.assertEqual(vu.kimlik_dogrula("9206"), "9206")
        for k in KOTU_KIMLIKLER + (None, 9206):
            with self.subTest(k=k), self.assertRaises(vu.VeriHatasi):
                vu.kimlik_dogrula(k)

    def test_kaynaktan_gelen_kotu_ilce_id_cikti_dokunulmamis(self):
        for k in ("../x", "/abs", "9206/../x", ""):
            with self.subTest(k=k):
                istemci = tv.SahteIstemci({f"{ADRES}/ilceler/506": [{"IlceID": k, "IlceAdi": "KOTU"}]})
                self._basarisiz_ve_dokunulmamis(vu.EmushafKaynak(istemci), "--dizin-yalniz")

    def test_kaynaktan_gelen_kotu_il_id_urlye_girmez(self):
        istemci = tv.SahteIstemci({f"{ADRES}/sehirler/2": [{"SehirID": "../x", "SehirAdi": "KOTU"}]})
        self._basarisiz_ve_dokunulmamis(vu.EmushafKaynak(istemci), "--dizin-yalniz")
        self.assertEqual(istemci.istekler, [f"{ADRES}/sehirler/2"])

    def test_cli_ilce_argumani(self):
        for k in ("../x", "/abs", "9206/../x", ""):
            with self.subTest(k=k):
                istemci = tv.SahteIstemci()
                self._basarisiz_ve_dokunulmamis(vu.EmushafKaynak(istemci), "--ilce", k)
                self.assertFalse([u for u in istemci.istekler if "/vakitler/" in u])

    def test_vakit_url_ve_onceki_yol(self):
        kaynak = vu.EmushafKaynak(tv.SahteIstemci())
        for k in ("../x", "/abs", "9206/../x", ""):
            with self.subTest(k=k):
                with self.assertRaises(vu.VeriHatasi):
                    kaynak.vakitler(k)
                with self.assertRaises(vu.VeriHatasi):
                    vu.onceki_gunleri_oku(self.tmp.name, k)

    def test_sema_dogrulamalari(self):
        for k in ("../x", "/abs", "9206/../x"):
            veri = tv.vakit_verisi(tv.gunler(date(2026, 11, 9), 10))
            veri["ilce_id"] = k
            dizin = {"surum": 1, "kaynak": "emushaf", "uretim": "x",
                     "iller": [{"il_id": "506", "il_adi": "A", "ilceler": [{"ilce_id": k, "ilce_adi": "B"}]}]}
            dizin_il = json.loads(json.dumps(dizin))
            dizin_il["iller"][0].update(il_id=k, ilceler=[{"ilce_id": "9206", "ilce_adi": "B"}])
            with self.subTest(k=k):
                for cagri in (lambda: vu.dogrula_vakit(veri, tv.BUGUN), lambda: vu.dogrula_dizin(dizin),
                              lambda: vu.dogrula_dizin(dizin_il)):
                    with self.assertRaises(vu.VeriHatasi):
                        cagri()


class AgSertlestirmeTesti(CiktiDokunulmamisTabani):
    def test_yalniz_https_yonlendirme(self):
        isleyici = vu.YalnizHttpsYonlendirme()
        istek = urllib.request.Request(f"{ADRES}/vakitler/9206")
        for hedef in ("http://ezanvakti.emushaf.net/x", "ftp://ornek.invalid/x", "file:///etc/passwd"):
            with self.subTest(hedef=hedef), self.assertRaises(vu.VeriHatasi):
                isleyici.redirect_request(istek, None, 302, "Found", {}, hedef)
        yeni = isleyici.redirect_request(istek, None, 302, "Found", {}, "https://ornek.invalid/y")
        self.assertEqual(yeni.full_url, "https://ornek.invalid/y")

    def test_yonlendirme_isleyicisi_kurulu(self):
        acici = urllib.request._opener  # install_opener'ın kurduğu genel açıcı (özel alan)
        self.assertTrue(any(isinstance(h, vu.YalnizHttpsYonlendirme) for h in acici.handlers))
        self.assertFalse(any(type(h) is urllib.request.HTTPRedirectHandler for h in acici.handlers))

    def _sahte_urlopen(self, boyut, istenen):
        class Yanit:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                istenen.append(n)
                return b"x" * (boyut if n < 0 else min(n, boyut))

        return lambda istek, timeout: Yanit()

    def test_yanit_ust_siniri(self):
        istenen = []
        with mock.patch.object(vu.urllib.request, "urlopen", self._sahte_urlopen(vu.AZAMI_YANIT + 10, istenen)):
            with self.assertRaises(vu.VeriHatasi):
                vu.ham_getir("https://ornek.invalid/x")
        self.assertEqual(istenen, [vu.AZAMI_YANIT + 1])  # sınırsız read() çağrılmadı
        with mock.patch.object(vu.urllib.request, "urlopen", self._sahte_urlopen(vu.AZAMI_YANIT, [])):
            self.assertEqual(len(vu.ham_getir("https://ornek.invalid/x")), vu.AZAMI_YANIT)

    def test_beklenmeyen_istisna_cikis_1_ve_dokunulmamis(self):
        class BozukKaynak:
            ad = "bozuk"

            def iller(self):
                raise RuntimeError("beklenmeyen")

        self._basarisiz_ve_dokunulmamis(BozukKaynak(), "--ilce", "9206")


class YeniYanitTekBasinaYeterliTesti(CiktiDokunulmamisTabani):
    """Kapı 2 TUR 1: önceki yayının tamponu kısa/boş/bayat yeni yanıtı gizleyemez."""

    def _onceki_tam(self):
        self.onceki = os.path.join(self.tmp.name, "onceki")
        os.makedirs(os.path.join(self.onceki, "vakitler"))
        with open(os.path.join(self.onceki, "vakitler", "9206.json"), "w", encoding="utf-8") as f:
            json.dump(tv.vakit_verisi(fikstur_gunleri()), f)  # 09.11-10.12

    def test_bos_yeni_yanit_tam_onceki(self):
        self._onceki_tam()
        kaynak = vu.EmushafKaynak(tv.SahteIstemci({f"{ADRES}/vakitler/9206": []}))
        self._basarisiz_ve_dokunulmamis(kaynak, "--ilce", "9206", "--onceki", self.onceki)

    def test_yalniz_gecmis_gunler_tam_onceki(self):
        self._onceki_tam()
        gecmis = tv.fikstur("vakitler_ornek.json")[:10]  # 09-18.11; bugün 20.11 -> hepsi budanır
        kaynak = vu.EmushafKaynak(tv.SahteIstemci({f"{ADRES}/vakitler/9206": gecmis}))
        simdi = datetime(2026, 11, 20, 6, 30, tzinfo=vu.TR)  # önceki yayın tek başına +20'ye uzanır
        self._basarisiz_ve_dokunulmamis(kaynak, "--ilce", "9206", "--onceki", self.onceki, simdi=simdi)


class MakullikTesti(unittest.TestCase):
    def _gunler(self, **degisen):
        return [dict(g, **degisen) for g in tv.gunler(date(2026, 11, 9), 10)]

    def test_gunluk_fark(self):
        g = self._gunler()
        g[5] = dict(g[5], ikindi="15:39")  # 15:34 -> 15:39 = 5 dk: geçer
        vu.makullik_denetle(g, [], [])
        g[5] = dict(g[5], ikindi="15:40")  # 6 dk
        with self.assertRaises(vu.VeriHatasi):
            vu.makullik_denetle(g, [], [])

    def test_ogle_bandi(self):
        for ogle in ("11:00", "14:30"):
            vu.makullik_denetle(self._gunler(ogle=ogle), [], [])
        for ogle in ("10:59", "14:31"):
            with self.subTest(ogle=ogle), self.assertRaises(vu.VeriHatasi):
                vu.makullik_denetle(self._gunler(ogle=ogle), [], [])

    def test_revizyon_farki_budanan_gunde_bakilmaz(self):
        g = self._gunler()
        eski_budanmis = [tv.gun("2026-11-01", ("01:00", "02:00", "03:00", "04:00", "05:00", "06:00"))]
        vu.makullik_denetle(g, eski_budanmis, [tv.gun("2026-11-01")] + g)

    def _calistir(self, onceki_gunler):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        onceki = os.path.join(tmp.name, "onceki")
        os.makedirs(os.path.join(onceki, "vakitler"))
        with open(os.path.join(onceki, "vakitler", "9206.json"), "w", encoding="utf-8") as f:
            json.dump(tv.vakit_verisi(onceki_gunler), f)
        cikti = os.path.join(tmp.name, "cikti")
        vu.calistir(vu.EmushafKaynak(tv.SahteIstemci()), cikti, onceki=onceki, ilce_idler=["9206"],
                    simdi=tv.SIMDI, kayit=lambda m: None)
        return cikti

    def test_onceki_yayinla_revizyon_farki_uctan_uca(self):
        gunler = fikstur_gunleri()
        gunler[4] = dict(gunler[4], aksam="18:00")  # fikstür 17:55 -> fark 5 dk: geçer
        self._calistir(gunler)
        gunler[4] = dict(gunler[4], aksam="18:01")  # 6 dk
        with self.assertRaises(vu.VeriHatasi) as bag:
            self._calistir(gunler)
        self.assertIn("ANKARA", str(bag.exception))
        self.assertIn("aksam", str(bag.exception))

    def test_il_sayisi_tam_calismada(self):
        with tempfile.TemporaryDirectory() as tmp:
            cikti = os.path.join(tmp, "cikti")
            with self.assertRaises(vu.VeriHatasi):
                vu.calistir(vu.EmushafKaynak(tv.SahteIstemci()), cikti, simdi=tv.SIMDI, kayit=lambda m: None)
            self.assertFalse(os.path.exists(cikti))
            with mock.patch.object(vu, "EN_AZ_IL", 2):
                vu.calistir(vu.EmushafKaynak(tv.SahteIstemci()), cikti, simdi=tv.SIMDI, kayit=lambda m: None)
            self.assertEqual(len(os.listdir(os.path.join(cikti, "vakitler"))), 5)
            self.assertEqual(vu.EN_AZ_IL, 81)


if __name__ == "__main__":
    unittest.main()
