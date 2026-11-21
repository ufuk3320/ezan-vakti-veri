"""vakit_uret.py uç durum testleri (ağsız, uykusuz). Çalıştırma: python -m unittest discover -s veri -v"""

import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_vakit_uret as tv  # noqa: E402  (yardımcılar: sahte istemci, fikstür, gün üreticiler)
import vakit_uret as vu  # noqa: E402

ADRES = vu.EmushafKaynak.ADRES
V9206 = f"{ADRES}/vakitler/9206"


def anlik_goruntu(klasor):
    """Klasördeki tüm dosyaların göreli yol -> bayt eşlemesi (dokunulmamışlık kanıtı)."""
    sonuc = {}
    for kok, _, adlar in os.walk(klasor):
        for ad in adlar:
            yol = os.path.join(kok, ad)
            with open(yol, "rb") as f:
                sonuc[os.path.relpath(yol, klasor)] = f.read()
    return sonuc


class CiktiDokunulmamisTabani(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cikti = os.path.join(self.tmp.name, "cikti")
        os.makedirs(os.path.join(self.cikti, "vakitler"))
        with open(os.path.join(self.cikti, "ilceler.json"), "w", encoding="utf-8") as f:
            f.write("ESKI-DIZIN")
        with open(os.path.join(self.cikti, "vakitler", "9206.json"), "w", encoding="utf-8") as f:
            f.write("ESKI-VAKIT")
        self.once = anlik_goruntu(self.cikti)

    def tearDown(self):
        self.tmp.cleanup()

    def _main(self, kaynak, *ek, simdi=tv.SIMDI):
        with mock.patch.object(vu, "datetime", wraps=datetime) as dt:
            dt.now.return_value = simdi
            return vu.main(["--cikti", self.cikti, *ek], kaynak=kaynak)

    def _basarisiz_ve_dokunulmamis(self, kaynak, *ek, simdi=tv.SIMDI):
        self.assertEqual(self._main(kaynak, *ek, simdi=simdi), 1)
        self.assertEqual(anlik_goruntu(self.cikti), self.once)
        self.assertFalse([a for a in os.listdir(self.tmp.name) if a.startswith(".vakit_gecici_")])


class EmushafYanitiBozuksaTesti(CiktiDokunulmamisTabani):
    def _vakit_yaniti(self, yanit):
        return vu.EmushafKaynak(tv.SahteIstemci({V9206: yanit}))

    def test_bos_liste(self):
        self._basarisiz_ve_dokunulmamis(self._vakit_yaniti([]), "--ilce", "9206")

    def test_json_degil_nesne_ya_da_dizge(self):
        for yanit in ({}, {"a": 1}, "bozuk", 5):
            with self.subTest(yanit=yanit):
                self._basarisiz_ve_dokunulmamis(self._vakit_yaniti(yanit), "--ilce", "9206")

    def test_json_null_yaniti(self):
        # Kaynak null dönerse `for g in None` TypeError verir; main bunu yakalamıyorsa kalıp hata düşer.
        self._basarisiz_ve_dokunulmamis(self._vakit_yaniti(None), "--ilce", "9206")

    def test_gun_kaydi_liste_olmayan_ogeler(self):
        for oge in (None, 5, "x", [1, 2]):
            with self.subTest(oge=oge):
                self._basarisiz_ve_dokunulmamis(self._vakit_yaniti([oge]), "--ilce", "9206")

    def test_alan_eksik_yatsi(self):
        yanit = tv.fikstur("vakitler_ornek.json")
        del yanit[4]["Yatsi"]
        self._basarisiz_ve_dokunulmamis(self._vakit_yaniti(yanit), "--ilce", "9206")

    def test_saat_alani_bos_ya_da_null(self):
        for deger in ("", None, 1938):
            yanit = tv.fikstur("vakitler_ornek.json")
            yanit[3]["Ikindi"] = deger
            with self.subTest(deger=deger):
                self._basarisiz_ve_dokunulmamis(self._vakit_yaniti(yanit), "--ilce", "9206")

    def test_dizin_yaniti_bos_il_listesi(self):
        kaynak = vu.EmushafKaynak(tv.SahteIstemci({f"{ADRES}/sehirler/2": []}))
        self._basarisiz_ve_dokunulmamis(kaynak, "--dizin-yalniz")

    def test_il_icin_bos_ilce_listesi(self):
        kaynak = vu.EmushafKaynak(tv.SahteIstemci({f"{ADRES}/ilceler/539": []}))
        self._basarisiz_ve_dokunulmamis(kaynak, "--dizin-yalniz")

    def test_yinelenen_ilce_id_calistirmada(self):
        # 9206, il 539'da da tekrar: dizin doğrulaması çıktıyı engellemeli.
        yeni = [{"IlceID": "9206", "IlceAdi": "KOPYA"}]
        kaynak = vu.EmushafKaynak(tv.SahteIstemci({f"{ADRES}/ilceler/539": yeni}))
        self._basarisiz_ve_dokunulmamis(kaynak, "--dizin-yalniz")

    def test_ayni_il_icinde_yinelenen_ilce(self):
        yeni = [{"IlceID": "9541", "IlceAdi": "A"}, {"IlceID": "9541", "IlceAdi": "B"}]
        kaynak = vu.EmushafKaynak(tv.SahteIstemci({f"{ADRES}/ilceler/539": yeni}))
        self._basarisiz_ve_dokunulmamis(kaynak, "--dizin-yalniz")


class SaatBicimiTesti(unittest.TestCase):
    def _dene(self, saat, alan="imsak"):
        g = tv.gunler(date(2026, 11, 9), 10)
        g[2] = dict(g[2], **{alan: saat})
        vu.dogrula_vakit(tv.vakit_verisi(g), tv.BUGUN)

    def test_bicim_hatalari(self):
        for s in ("24:00", "24:01", "6:05", "06:5", "6:5", "06:05:00", " 06:05", "06:05 ", "-6:05", "06-05",
                  "0605", "ab:cd", "٠٦:٠٥", None, 605, 6.05, ["06:05"]):
            with self.subTest(s=s), self.assertRaises(vu.VeriHatasi):
                self._dene(s)

    def test_sonda_satir_sonu(self):
        # Python'da `$` sondaki "\n"i de kabul eder: "06:05\n" doğrulamadan geçmemeli.
        for s in ("06:05\n", "06:05\r\n"):
            with self.subTest(s=repr(s)), self.assertRaises(vu.VeriHatasi):
                self._dene(s)

    def test_gecerli_sinirlar(self):
        g = tv.gunler(date(2026, 11, 9), 10)
        g[0] = tv.gun(g[0]["tarih"], ("00:00", "00:01", "12:00", "18:00", "20:00", "23:59"))
        vu.dogrula_vakit(tv.vakit_verisi(g), tv.BUGUN)

    def test_esit_saat_ve_gece_yarisi_asimi(self):
        # Yatsı 00:10 (ertesi gün) olursa metin sırası bozulur; şema bunu reddeder (belgelenmiş davranış).
        with self.assertRaises(vu.VeriHatasi):
            self._dene("00:10", alan="yatsi")

    def test_tarih_sonda_satir_sonu(self):
        g = tv.gunler(date(2026, 11, 9), 10)
        g[1] = dict(g[1], tarih=g[1]["tarih"] + "\n")
        with self.assertRaises(vu.VeriHatasi):
            vu.dogrula_vakit(tv.vakit_verisi(g), tv.BUGUN)


class ArdisiklikTesti(unittest.TestCase):
    def test_yil_gecisi_ardisik(self):
        vu.dogrula_vakit(tv.vakit_verisi(tv.gunler(date(2026, 12, 28), 12)), date(2026, 12, 30))  # son 2027-01-08

    def test_yil_gecisi_bosluk_ve_tekrar(self):
        g = tv.gunler(date(2026, 12, 28), 12)
        tarihler = [x["tarih"] for x in g]
        self.assertIn("2026-12-31", tarihler)
        self.assertIn("2027-01-01", tarihler)
        i = tarihler.index("2027-01-01")
        for ad, liste in (("bosluk", g[:i] + g[i + 1:]), ("tekrar", g[:i + 1] + g[i:])):
            with self.subTest(ad), self.assertRaises(vu.VeriHatasi):
                vu.dogrula_vakit(tv.vakit_verisi(liste), date(2026, 12, 30))

    def test_ay_gecisi_ve_artik_yil(self):
        vu.dogrula_vakit(tv.vakit_verisi(tv.gunler(date(2028, 2, 27), 10)), date(2028, 2, 28))  # 02-29 var
        vu.dogrula_vakit(tv.vakit_verisi(tv.gunler(date(2027, 2, 27), 10)), date(2027, 2, 28))  # 02-28 -> 03-01
        artik = tv.gunler(date(2028, 2, 27), 10)
        atlayan = [x for x in artik if x["tarih"] != "2028-02-29"]  # artık günü atla
        with self.assertRaises(vu.VeriHatasi):
            vu.dogrula_vakit(tv.vakit_verisi(atlayan), date(2028, 2, 28))

    def test_olmayan_tarih_29_subat(self):
        g = tv.gunler(date(2027, 2, 27), 10)
        g[2] = dict(g[2], tarih="2027-02-29")
        with self.assertRaises(vu.VeriHatasi):
            vu.dogrula_vakit(tv.vakit_verisi(g), date(2027, 2, 28))

    def test_ilk_gun_gecmiste_olabilir_ama_tek_gun_yetmez(self):
        with self.assertRaises(vu.VeriHatasi):
            vu.dogrula_vakit(tv.vakit_verisi(tv.gunler(date(2026, 11, 9), 1)), tv.BUGUN)


class YediGunSinirTesti(unittest.TestCase):
    def test_dogrulayicida_alti_hata_yedi_gecer(self):
        bugun = date(2026, 11, 10)
        with self.assertRaises(vu.VeriHatasi):
            vu.dogrula_vakit(tv.vakit_verisi(tv.gunler(bugun, 7)), bugun)  # son bugün+6
        vu.dogrula_vakit(tv.vakit_verisi(tv.gunler(bugun, 8)), bugun)  # son bugün+7

    def test_uctan_uca_fikstur_siniri(self):
        # Fikstür son günü 10.12. Yeni yanıt tek başına bugün+YENI_ILERI_GUN(14)'e ulaşmalı:
        # bugün 26.11 -> +14 geçer; 27.11 -> +13 hata. (Uçtan uca +7 sınırı artık 14 kuralının gölgesinde.)
        self.assertEqual(vu.YENI_ILERI_GUN, 14)
        for gun_no, beklenen_hata in ((26, False), (27, True)):
            with self.subTest(bugun=gun_no), tempfile.TemporaryDirectory() as tmp:
                cikti = os.path.join(tmp, "cikti")
                simdi = datetime(2026, 11, gun_no, 6, 30, tzinfo=vu.TR)
                cagri = lambda: vu.calistir(vu.EmushafKaynak(tv.SahteIstemci()), cikti, ilce_idler=["9206"],
                                            simdi=simdi, kayit=lambda m: None)
                if beklenen_hata:
                    with self.assertRaises(vu.VeriHatasi):
                        cagri()
                    self.assertFalse(os.path.exists(cikti))
                else:
                    cagri()
                    self.assertTrue(os.path.exists(os.path.join(cikti, "vakitler", "9206.json")))

    @staticmethod
    def _fikstur_devami(ilk, son):
        """ilk..son günleri: fikstürde olan günler fikstür değeriyle, sonrası fikstürün son günü değerleriyle."""
        fg = {g["tarih"]: g for g in (vu.gun_cevir(h) for h in tv.fikstur("vakitler_ornek.json"))}
        son_fikstur = fg[max(fg)]
        liste, t = [], ilk
        while t <= son:
            iso = t.isoformat()
            liste.append(fg.get(iso) or dict(son_fikstur, tarih=iso))
            t += timedelta(days=1)
        return liste

    def test_onceki_yayin_kisa_yaniti_tamamlamaz(self):
        # Yeni yanıt bugün+6'da biter; önceki yayın bugün+33'e kadar uzansa da tamponu yeni yanıtı
        # gizleyemez: çıkış 1, çıktı bayt bayt aynı (bayat veri yeni "uretim" ile yeniden yayınlanmaz).
        with tempfile.TemporaryDirectory() as tmp:
            onceki = os.path.join(tmp, "onceki")
            os.makedirs(os.path.join(onceki, "vakitler"))
            with open(os.path.join(onceki, "vakitler", "9206.json"), "w", encoding="utf-8") as f:
                json.dump(tv.vakit_verisi(self._fikstur_devami(date(2026, 11, 11), date(2026, 12, 15))), f)
            cikti = os.path.join(tmp, "cikti")
            os.makedirs(os.path.join(cikti, "vakitler"))
            with open(os.path.join(cikti, "vakitler", "9206.json"), "w", encoding="utf-8") as f:
                f.write("ESKI-VAKIT")
            once = anlik_goruntu(cikti)
            kisa = tv.fikstur("vakitler_ornek.json")[:10]  # 09-18.11
            kaynak = vu.EmushafKaynak(tv.SahteIstemci({V9206: kisa}))
            simdi = datetime(2026, 11, 12, 6, 30, tzinfo=vu.TR)  # 18.11 = +6
            with mock.patch.object(vu, "datetime", wraps=datetime) as dt:
                dt.now.return_value = simdi
                kod = vu.main(["--cikti", cikti, "--onceki", onceki, "--ilce", "9206"], kaynak=kaynak)
            self.assertEqual(kod, 1)
            self.assertEqual(anlik_goruntu(cikti), once)

    def test_saat_dilimi_turkiye_gunune_gore(self):
        # 10.11 21:30 UTC = 11.11 00:30 TR: bugün 11.11 sayılır (son gün 18.11 = +7, bugün-1 = 10.11).
        simdi = datetime(2026, 11, 10, 21, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            cikti = os.path.join(tmp, "cikti")
            vu.calistir(vu.EmushafKaynak(tv.SahteIstemci()), cikti, ilce_idler=["9206"], simdi=simdi,
                        kayit=lambda m: None)
            with open(os.path.join(cikti, "vakitler", "9206.json"), encoding="utf-8") as f:
                veri = json.load(f)
            self.assertEqual(veri["gunler"][0]["tarih"], "2026-11-10")
            self.assertEqual(veri["uretim"], "2026-11-11T00:30:00+03:00")


class BudamaTesti(unittest.TestCase):
    def test_sinir_tam_bugun_eksi_bir(self):
        bugun = date(2026, 11, 10)
        onceki = [tv.gun(f"2026-11-0{d}") for d in (7, 8, 9)]
        sonuc = [g["tarih"] for g in vu.birlestir(onceki, [], bugun)]
        self.assertEqual(sonuc, ["2026-11-09"])  # 08.11 (bugün-2) gider, 09.11 (bugün-1) kalır

    def test_sinir_ay_ve_yil_basinda(self):
        bugun = date(2027, 1, 1)
        onceki = [tv.gun("2026-12-30"), tv.gun("2026-12-31"), tv.gun("2027-01-01")]
        self.assertEqual([g["tarih"] for g in vu.birlestir(onceki, [], bugun)], ["2026-12-31", "2027-01-01"])
        bugun = date(2026, 3, 1)  # artık olmayan yıl: bugün-1 = 28 Şubat
        onceki = [tv.gun("2026-02-27"), tv.gun("2026-02-28"), tv.gun("2026-03-01")]
        self.assertEqual([g["tarih"] for g in vu.birlestir(onceki, [], bugun)], ["2026-02-28", "2026-03-01"])

    def test_yeni_yanittaki_eski_gun_de_budanir(self):
        bugun = date(2026, 11, 10)
        sonuc = [g["tarih"] for g in vu.birlestir([], [tv.gun("2026-11-05"), tv.gun("2026-11-09")], bugun)]
        self.assertEqual(sonuc, ["2026-11-09"])

    def test_onceki_gelecek_gunu_korunur_eski_gunu_silinir(self):
        bugun = date(2026, 11, 10)
        onceki = [tv.gun("2026-11-05"), tv.gun("2026-11-20"), tv.gun("2026-11-21")]
        yeni = [tv.gun("2026-11-10")]
        sonuc = [g["tarih"] for g in vu.birlestir(onceki, yeni, bugun)]
        self.assertEqual(sonuc, ["2026-11-10", "2026-11-20", "2026-11-21"])

    def test_ayni_tarihte_yeni_kazanir_ve_girdi_degismez(self):
        bugun = date(2026, 11, 10)
        eski = tv.gun("2026-11-10", ("01:00", "02:00", "03:00", "04:00", "05:00", "06:00"))
        yeni = tv.gun("2026-11-10")
        onceki_liste, yeni_liste = [eski], [yeni]
        self.assertEqual(vu.birlestir(onceki_liste, yeni_liste, bugun), [yeni])
        self.assertEqual((onceki_liste, yeni_liste), ([eski], [yeni]))

    def test_uctan_uca_ayni_tarih_ve_budama(self):
        with tempfile.TemporaryDirectory() as tmp:
            onceki = os.path.join(tmp, "onceki")
            os.makedirs(os.path.join(onceki, "vakitler"))
            # Eski 10.11 değerleri fikstürden 2 dk sapık (06:10 -> yeni 06:12; <= 5 dk: yeni kazanır).
            fg = YediGunSinirTesti._fikstur_devami(date(2026, 11, 9), date(2026, 12, 15))
            eski_gun = dict(fg[1], imsak="06:10")
            liste = [dict(fg[0], tarih="2026-11-07"), dict(fg[0], tarih="2026-11-08"), fg[0], eski_gun] + fg[2:]
            with open(os.path.join(onceki, "vakitler", "9206.json"), "w", encoding="utf-8") as f:
                json.dump(tv.vakit_verisi(liste), f)
            cikti = os.path.join(tmp, "cikti")
            vu.calistir(vu.EmushafKaynak(tv.SahteIstemci()), cikti, onceki=onceki, ilce_idler=["9206"],
                        simdi=tv.SIMDI, kayit=lambda m: None)
            with open(os.path.join(cikti, "vakitler", "9206.json"), encoding="utf-8") as f:
                gunler = {g["tarih"]: g for g in json.load(f)["gunler"]}
            self.assertEqual(min(gunler), "2026-11-09")
            self.assertEqual(max(gunler), "2026-12-15")
            self.assertEqual(gunler["2026-11-10"]["imsak"], vu.gun_cevir(tv.fikstur("vakitler_ornek.json")[1])["imsak"])
            self.assertNotEqual(gunler["2026-11-10"]["imsak"], "06:10")


class RevizyonFarkiAsildiTesti(CiktiDokunulmamisTabani):
    def test_buyuk_revizyon_cikis_1_ve_cikti_dokunulmamis(self):
        # Önceki yayında 10.11 imsak 01:00, yeni yanıtta 06:12 (> 5 dk): çalışma başarısız, çıktı yazılmaz.
        onceki = os.path.join(self.tmp.name, "onceki")
        os.makedirs(os.path.join(onceki, "vakitler"))
        fg = YediGunSinirTesti._fikstur_devami(date(2026, 11, 9), date(2026, 11, 22))
        fg[1] = dict(fg[1], imsak="01:00")
        with open(os.path.join(onceki, "vakitler", "9206.json"), "w", encoding="utf-8") as f:
            json.dump(tv.vakit_verisi(fg), f)
        self._basarisiz_ve_dokunulmamis(vu.EmushafKaynak(tv.SahteIstemci()), "--ilce", "9206", "--onceki", onceki)


class OncekiYayinBozukTesti(CiktiDokunulmamisTabani):
    def _onceki_yaz(self, icerik, ilce="9206"):
        self.onceki = os.path.join(self.tmp.name, "onceki")
        os.makedirs(os.path.join(self.onceki, "vakitler"), exist_ok=True)
        with open(os.path.join(self.onceki, "vakitler", f"{ilce}.json"), "w", encoding="utf-8") as f:
            f.write(icerik if isinstance(icerik, str) else json.dumps(icerik))

    def _dene(self, icerik):
        self._onceki_yaz(icerik)
        self._basarisiz_ve_dokunulmamis(vu.EmushafKaynak(tv.SahteIstemci()), "--ilce", "9206",
                                        "--onceki", self.onceki)

    def test_bozuk_json(self):
        for icerik in ("{bozuk", "", "[1,", "\x00\x01"):
            with self.subTest(icerik=icerik):
                self._dene(icerik)

    def test_json_gecerli_ama_sema_bozuk(self):
        ok = tv.vakit_verisi(tv.gunler(date(2026, 11, 9), 10))
        for ad, icerik in (("liste", [1, 2]), ("null", None), ("gunler_yok", {"ilce_id": "9206"}),
                           ("gunler_liste_degil", dict(ok, gunler="x")),
                           ("baska_ilce", dict(ok, ilce_id="9541"))):
            with self.subTest(ad):
                self._dene(icerik)

    def test_onceki_gunler_icinde_bozuk_gun(self):
        ok = tv.vakit_verisi(tv.gunler(date(2026, 11, 11), 12) + [{"tarih": "2026-11-25"}])
        self._dene(ok)

    def test_onceki_gunler_oge_sozluk_degil(self):
        # Önceki yayında gunler = [5]: birlestir g["tarih"] TypeError verir; VeriHatasi/hata kodu beklenir.
        self._dene(dict(tv.vakit_verisi([]), gunler=[5]))

    def test_onceki_klasor_yok_veya_ilce_dosyasi_yok_ise_bos_sayilir(self):
        with tempfile.TemporaryDirectory() as tmp:
            for onceki in (None, "", os.path.join(tmp, "yok")):
                with self.subTest(onceki=onceki):
                    self.assertEqual(vu.onceki_gunleri_oku(onceki, "9206"), [])


class YenidenDenemeKaliciHataTesti(CiktiDokunulmamisTabani):
    def _istemci(self, getir):
        self.bekleme = []
        saat = [100.0]

        def bekle(sn):
            self.bekleme.append(sn)
            saat[0] += sn

        return vu.NazikIstemci(getir=getir, bekle=bekle, saat=lambda: saat[0])

    def test_kalici_ag_hatasi_istisna_ve_dort_deneme(self):
        cagri = []

        def getir(url):
            cagri.append(url)
            raise OSError("kopuk")

        istemci = self._istemci(getir)
        with self.assertRaises(vu.VeriHatasi) as ctx:
            istemci.json_getir("https://ornek.invalid/x")
        self.assertEqual(len(cagri), 4)
        self.assertIn("kopuk", str(ctx.exception))

    def test_gecersiz_utf8_ve_json_degil_yaniti(self):
        for govde in (b"\xff\xfe\x00", b"<html>502</html>", b""):
            with self.subTest(govde=govde):
                cagri = []
                istemci = self._istemci(lambda url, c=cagri: (c.append(url), govde)[1])
                with self.assertRaises(vu.VeriHatasi):
                    istemci.json_getir("u")
                self.assertEqual(len(cagri), 4)

    def test_ilk_denemede_basari_bekleme_yok(self):
        istemci = self._istemci(lambda url: b"[]")
        self.assertEqual(istemci.json_getir("u"), [])
        self.assertEqual(self.bekleme, [])

    def test_son_denemede_basari(self):
        cagri = []

        def getir(url):
            cagri.append(url)
            if len(cagri) < 4:
                raise OSError("kopuk")
            return b"[7]"

        self.assertEqual(self._istemci(getir).json_getir("u"), [7])
        self.assertEqual(self.bekleme, [1, 2, 4])  # üstel bekleme aralık şartını zaten karşılar

    def test_kalici_hata_main_sifirdan_farkli_cikis_ve_cikti_dokunulmamis(self):
        def getir(url):
            raise OSError("kopuk")

        kaynak = vu.EmushafKaynak(self._istemci(getir))
        self._basarisiz_ve_dokunulmamis(kaynak, "--dizin-yalniz")


class IlcelerDogrulamaTesti(unittest.TestCase):
    def _dizin(self):
        return {"surum": 1, "kaynak": "emushaf", "uretim": "2026-11-10T06:30:00+03:00",
                "iller": [{"il_id": "506", "il_adi": "ANKARA",
                           "ilceler": [{"ilce_id": "9206", "ilce_adi": "ANKARA"}]}]}

    def test_gecerli(self):
        vu.dogrula_dizin(self._dizin())

    def test_ust_alan_hatalari(self):
        for alan, deger in (("surum", 2), ("surum", None), ("kaynak", ""), ("uretim", " "), ("iller", []),
                            ("iller", None), ("iller", {})):
            d = self._dizin()
            d[alan] = deger
            with self.subTest(alan=alan, deger=deger), self.assertRaises(vu.VeriHatasi):
                vu.dogrula_dizin(d)
        for veri in (None, [], "x"):
            with self.subTest(veri=veri), self.assertRaises(vu.VeriHatasi):
                vu.dogrula_dizin(veri)

    def test_il_ve_ilce_kaydi_hatalari(self):
        degisiklikler = [
            lambda d: d["iller"][0].update(il_id=""),
            lambda d: d["iller"][0].update(il_adi=None),
            lambda d: d["iller"][0].update(ilceler=[]),
            lambda d: d["iller"][0].update(ilceler=None),
            lambda d: d["iller"][0]["ilceler"][0].update(ilce_id=""),
            lambda d: d["iller"][0]["ilceler"][0].update(ilce_id=9206),
            lambda d: d["iller"][0]["ilceler"][0].update(ilce_adi=" "),
        ]
        for i, degistir in enumerate(degisiklikler):
            d = self._dizin()
            degistir(d)
            with self.subTest(i=i), self.assertRaises(vu.VeriHatasi):
                vu.dogrula_dizin(d)

    def test_yinelenen_ilce_ayni_ya_da_farkli_il(self):
        ayni = self._dizin()
        ayni["iller"][0]["ilceler"].append({"ilce_id": "9206", "ilce_adi": "B"})
        farkli = self._dizin()
        farkli["iller"].append({"il_id": "539", "il_adi": "X", "ilceler": [{"ilce_id": "9206", "ilce_adi": "Y"}]})
        for ad, d in (("ayni_il", ayni), ("farkli_il", farkli)):
            with self.subTest(ad), self.assertRaises(vu.VeriHatasi):
                vu.dogrula_dizin(d)


class TamCalismadaErisilemeyenIlceTesti(CiktiDokunulmamisTabani):
    """Tam çalışmada kaynağa erişilemeyen ilçe atlanır; bozuk veri ve --ilce çalışması yine fail-closed."""

    def setUp(self):
        super().setUp()
        yama = mock.patch.object(vu, "EN_AZ_IL", 1)  # fikstür dizininde 2 il var
        yama.start()
        self.addCleanup(yama.stop)

    def _erisilemez(self, *ilceler):
        hata = vu.KaynakErisimHatasi("HTTP Error 502: Bad Gateway")
        return vu.EmushafKaynak(tv.SahteIstemci({f"{ADRES}/vakitler/{i}": hata for i in ilceler}))

    def test_istemci_kalici_hatada_erisim_hatasi_firlatir(self):
        def getir(url):
            raise OSError("504")

        istemci = vu.NazikIstemci(getir=getir, bekle=lambda sn: None, saat=lambda: 0.0)
        with self.assertRaises(vu.KaynakErisimHatasi):
            istemci.json_getir("u")

    def test_erisilemeyen_ilce_atlanir_digerleri_yazilir_eski_dosya_kalir(self):
        self.assertEqual(self._main(self._erisilemez("9206")), 0)
        yazilan = sorted(os.listdir(os.path.join(self.cikti, "vakitler")))
        self.assertEqual(yazilan, ["9205.json", "9206.json", "9207.json", "9535.json", "9541.json"])
        with open(os.path.join(self.cikti, "vakitler", "9206.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "ESKI-VAKIT")  # atlanan ilçenin önceki dosyası olduğu gibi
        with open(os.path.join(self.cikti, "ilceler.json"), encoding="utf-8") as f:
            vu.dogrula_dizin(json.load(f))  # dizin yine yayımlandı

    def test_sinir_asilirsa_hicbir_sey_yazilmaz(self):
        with mock.patch.object(vu, "EN_COK_ATLANAN", 1):
            self._basarisiz_ve_dokunulmamis(self._erisilemez("9205", "9206"))

    def test_sinirda_yayin_yapilir(self):
        with mock.patch.object(vu, "EN_COK_ATLANAN", 2):
            self.assertEqual(self._main(self._erisilemez("9205", "9206")), 0)

    def test_bozuk_veri_tam_calismada_da_durdurur(self):
        bozuk = tv.fikstur("vakitler_ornek.json")
        bozuk[2] = dict(bozuk[2], Ogle=bozuk[2]["Gunes"])  # artmayan saat
        kaynak = vu.EmushafKaynak(tv.SahteIstemci({f"{ADRES}/vakitler/9541": bozuk}))
        self._basarisiz_ve_dokunulmamis(kaynak)

    def test_ilce_listesiyle_calismada_erisim_hatasi_durdurur(self):
        self._basarisiz_ve_dokunulmamis(self._erisilemez("9541"), "--ilce", "9206", "--ilce", "9541")

    def test_dizin_alinamazsa_durdurur(self):
        kaynak = vu.EmushafKaynak(tv.SahteIstemci({f"{ADRES}/ilceler/539": vu.KaynakErisimHatasi("504")}))
        self._basarisiz_ve_dokunulmamis(kaynak)


class IsAkisiMetinTesti(unittest.TestCase):
    """GERÇEK YAML ayrıştırması DEĞİLDİR; mevcut yapısal denetimi tamamlayan stdlib metin denetimleri."""

    @classmethod
    def setUpClass(cls):
        with open(tv.IS_AKISI, encoding="utf-8") as f:
            cls.metin = f.read()
        cls.satirlar = cls.metin.splitlines()

    def _adim_sirasi(self, ad):
        for i, s in enumerate(self.satirlar):
            if s.strip() == f"- name: {ad}":
                return i
        self.fail(f"adım yok: {ad}")

    def test_push_yalniz_gh_pages(self):
        pushlar = [s.strip() for s in self.satirlar if re.search(r"\bgit\b.*\bpush\b", s)]
        self.assertEqual(pushlar, ["git push origin gh-pages"])

    def test_zorla_ve_tehlikeli_komut_yok(self):
        for yasak in ("--force", "push -f", "--force-with-lease", "reset --hard", "rm -rf", "pull_request",
                      "pull_request_target", "workflow_run", "permissions: write-all", "--no-verify"):
            self.assertNotIn(yasak, self.metin, yasak)

    def test_main_dalina_yayin_yok(self):
        self.assertNotRegex(self.metin, r"push\s+\S+\s+(main|master|HEAD)\b")
        self.assertNotRegex(self.metin, r"checkout\s+(-b\s+)?(main|master)\b")

    def test_adim_sirasi_testler_once_yayin_en_son(self):
        sira = [self._adim_sirasi(a) for a in ("Betik testleri", "gh-pages dalını hazırla", "Vakitleri üret",
                                               "gh-pages dalına yayınla")]
        self.assertEqual(sira, sorted(sira))

    def test_uretim_komutu_onceki_ve_cikti_ayri_klasorler(self):
        uret = [s for s in self.satirlar if "vakit_uret.py" in s]
        self.assertEqual(len(uret), 1)
        self.assertIn('--onceki "$RUNNER_TEMP/yayin"', uret[0])
        self.assertIn('--cikti "$RUNNER_TEMP/yeni"', uret[0])
        self.assertNotIn("--ilce", uret[0])  # tüm ilçeler

    def test_testler_yayindan_once_ve_unittest_komutu(self):
        self.assertIn("run: python -m unittest discover -s veri -v", self.satirlar_strip())

    def satirlar_strip(self):
        return [s.strip() for s in self.satirlar]

    def test_yayin_adimi_degisiklik_yoksa_cikar_ve_hata_durdurur(self):
        self.assertEqual(self.metin.count("set -eu"), 2)  # hazırlık + yayın bash adımları
        self.assertIn("git diff --cached --quiet", self.metin)
        self.assertLess(self.metin.index("git diff --cached --quiet"), self.metin.index("commit -q"))
        self.assertLess(self.metin.index("commit -q"), self.metin.index("git push"))

    def test_gh_pages_dali_sabit_ve_calisma_agaci_runner_temp(self):
        self.assertIn('YAYIN="$RUNNER_TEMP/yayin"', self.metin)
        self.assertIn("git worktree add -B gh-pages", self.metin)
        self.assertIn("git worktree add --orphan -b gh-pages", self.metin)
        self.assertIn('cd "$RUNNER_TEMP/yayin"', self.metin)

    def test_zaman_asimi_ve_sabit_calistirici(self):
        m = re.search(r"^    timeout-minutes: (\d+)$", self.metin, re.M)
        self.assertIsNotNone(m)
        self.assertLessEqual(int(m.group(1)), 360)
        self.assertRegex(self.metin, r"runs-on: ubuntu-(latest|\d+\.\d+)")

    def test_cron_alanlari_gecerli_aralikta(self):
        cron = re.search(r"cron: '(\S+) (\S+) (\S+) (\S+) (\S+)'", self.metin)
        self.assertIsNotNone(cron)
        dk, saat, _, _, hafta = cron.groups()
        self.assertTrue(dk.isdigit() and 0 <= int(dk) <= 59)
        self.assertTrue(saat.isdigit() and 0 <= int(saat) <= 23)
        self.assertTrue(hafta.isdigit() and 0 <= int(hafta) <= 7)

    def test_baglamdan_girdi_enjeksiyonu_yok(self):
        self.assertNotIn("${{", self.metin)  # run adımlarına ifade gömülmemiş

    def test_ortam_degiskeni_sirri_ve_pip_yok(self):
        for yasak in ("pip install", "GITHUB_TOKEN", "token:", "curl ", "wget "):
            self.assertNotIn(yasak, self.metin, yasak)

    def test_commit_kimligi_bot(self):
        self.assertIn('user.name="github-actions[bot]"', self.metin)
        self.assertRegex(self.metin, r'user\.email="\d+\+github-actions\[bot\]@users\.noreply\.github\.com"')


if __name__ == "__main__":
    unittest.main()
