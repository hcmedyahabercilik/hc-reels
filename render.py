#!/usr/bin/env python3
"""HC Medya Habercilik - Reels uretici.

Bir haberi (baslik, ozet, kategori, istege bagli fotograf) 1080x1920, 30 fps,
yaklasik 15 saniyelik dikey bir videoya cevirir. Kareler Pillow ile cizilir,
FFmpeg ile H.264 + AAC olarak kodlanir. Muzik klasorunde dosya varsa biri
secilip yumusak giris/cikisla eklenir; yoksa sessiz ses izi konur.

Kullanim:
  python3 render.py --json haber.json --out cikti.mp4
haber.json: {"baslik": "...", "ozet": "...", "kategori": "GUNDEM",
             "gelisme": false, "foto_url": "", "tarih": "18 KASIM 2026 · 14:30",
             "id": "benzersiz-ad"}
"""
import argparse, hashlib, json, math, os, random, subprocess, sys, urllib.request, io
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
SURE = 15.0
NAVY = (14, 26, 43)
NAVY2 = (22, 38, 62)
RED = (227, 38, 46)
AMBER = (242, 184, 75)
LIGHT = (244, 245, 247)
GRAY = (58, 69, 86)
MUTED = (154, 167, 186)
WHITE = (255, 255, 255)

KOK = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(KOK, "fonts")


def font(adlar, boyut):
    for ad in adlar:
        for yol in (os.path.join(FONT_DIR, ad), ad):
            if os.path.exists(yol):
                return ImageFont.truetype(yol, boyut)
    return ImageFont.truetype("DejaVuSans-Bold.ttf", boyut)


BASLIK_F = ["BarlowCondensed-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"]
BASLIK_XF = ["BarlowCondensed-ExtraBold.ttf", "BarlowCondensed-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"]
METIN_F = ["Barlow-Regular.ttf", "Inter-Regular.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
METIN_BF = ["Barlow-SemiBold.ttf", "Inter-SemiBold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def ust(s):
    return s.replace("i", "İ").replace("ı", "I").upper()


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    t = max(0.0, min(1.0, t))
    return 3 * t * t - 2 * t * t * t


def sar(metin, f, genislik):
    satirlar, cur = [], ""
    for kelime in metin.split():
        deneme = (cur + " " + kelime).strip()
        if f.getlength(deneme) <= genislik or not cur:
            cur = deneme
        else:
            satirlar.append(cur)
            cur = kelime
    if cur:
        satirlar.append(cur)
    return satirlar


def logo(boyut, renk=WHITE):
    """HC logosu: C yayi, H dikmeleri, kirmizi yatay cizgi (vektorden cizilir)."""
    olcek = 4
    w, h = int(210 * boyut / 200) * olcek, boyut * olcek
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    k = h / 200.0
    cx, cy, r = 105 * k, 100 * k, 80 * k
    sw = int(22 * k)
    d.arc([cx - r - sw / 2, cy - r - sw / 2, cx + r + sw / 2, cy + r + sw / 2], 42.4, 317.6, fill=renk, width=sw)
    hw = int(18 * k)
    for x in (74, 116):
        d.rectangle([x * k - hw / 2, 62 * k, x * k + hw / 2, 138 * k], fill=renk)
    d.rectangle([65 * k, 100 * k - hw / 2, 190 * k, 100 * k + hw / 2], fill=RED)
    d.rectangle([190 * k, 88 * k, 206 * k, 112 * k], fill=RED)
    return im.resize((w // olcek, h // olcek), Image.LANCZOS)


def chip(metin, f, bg, fg, pad=(22, 12)):
    tw = int(f.getlength(metin))
    asc, desc = f.getmetrics()
    im = Image.new("RGBA", (tw + pad[0] * 2, asc + desc + pad[1] * 2), bg + (255,))
    ImageDraw.Draw(im).text((pad[0], pad[1]), metin, font=f, fill=fg)
    return im


def foto_indir(url):
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 hc-reels"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return Image.open(io.BytesIO(r.read())).convert("RGB")
    except Exception as e:
        print("foto indirilemedi:", e, file=sys.stderr)
        return None


def kirp_doldur(im, w, h):
    ow, oh = im.size
    s = max(w / ow, h / oh)
    im = im.resize((int(ow * s) + 1, int(oh * s) + 1), Image.LANCZOS)
    x = (im.width - w) // 2
    y = (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def muzik_sec(seed):
    klasor = os.path.join(KOK, "music")
    if not os.path.isdir(klasor):
        return None
    dosyalar = sorted(f for f in os.listdir(klasor) if f.lower().endswith((".mp3", ".m4a", ".wav", ".ogg")))
    if not dosyalar:
        return None
    return os.path.join(klasor, dosyalar[seed % len(dosyalar)])


def uret(h, cikti):
    baslik = ust(h.get("baslik", "").strip())
    ozet = h.get("ozet", "").strip()
    kat = ust(h.get("kategori", "GÜNDEM") or "GÜNDEM")
    gel = bool(h.get("gelisme"))
    tarih = h.get("tarih", "")
    seed = int(hashlib.md5((baslik + ozet).encode()).hexdigest()[:8], 16)
    rnd = random.Random(seed)

    ust_renk = AMBER if gel else RED
    ust_metin = "GELİŞME" if gel else "SON DAKİKA"
    kat_metin = ("GELİŞME · " + kat) if gel else kat

    # --- fontlar ve sabit katmanlar ---
    f_chip = font(BASLIK_F, 46)
    f_kat = font(BASLIK_F, 38)
    f_tarih = font(BASLIK_F, 34)
    f_marka = font(BASLIK_F, 40)
    f_ozet = font(METIN_F, 44)
    f_tick = font(BASLIK_F, 40)
    ob = 96
    f_outro1 = font(BASLIK_XF, ob)
    while f_outro1.getlength('HC MEDYA HABERCİLİK') > W - 220 and ob > 50:
        ob -= 4
        f_outro1 = font(BASLIK_XF, ob)
    f_outro2 = font(METIN_BF, 44)

    # Instagram Reels guvenli alani: sagda ~210 px dugmeler, altta ~330 px hesap adi/aciklama
    TW = 780
    ALT = 1400
    TICK_Y = 1420
    boy = 96
    f_b = font(BASLIK_XF, boy)
    bas_sat = sar(baslik, f_b, TW)
    while len(bas_sat) > 3 and boy > 64:
        boy -= 6
        f_b = font(BASLIK_XF, boy)
        bas_sat = sar(baslik, f_b, TW)
    lh = int(boy * 1.02)
    ozet_sat = sar(ozet, f_ozet, TW)

    foto = foto_indir(h.get("foto_url", ""))
    UST_H = 720  # foto sadece panelin ustunde gorunur; kucuk alan = buyutme yok, net goruntu
    if foto:
        foto = kirp_doldur(foto, int(W * 1.16), int(UST_H * 1.16))

    # ust arka plan (fotografsiz): lacivert + capraz cizgiler + filigran
    arka = Image.new("RGB", (W, UST_H), NAVY)
    ad = ImageDraw.Draw(arka)
    for i in range(-UST_H, W, 70):
        ad.line([(i, UST_H), (i + UST_H, 0)], fill=NAVY2, width=18)
    f_wm = font(BASLIK_XF, 300)
    wm = Image.new("RGBA", (W * 2, 360), (0, 0, 0, 0))
    ImageDraw.Draw(wm).text((0, 0), kat, font=f_wm, fill=(255, 255, 255, 14))

    # alttan koyulasan gradyan (yazi okunurlugu icin)
    grad = Image.new("L", (1, UST_H))
    for y in range(UST_H):
        grad.putpixel((0, y), int(200 * max(0, (y - UST_H * 0.45) / (UST_H * 0.55)) ** 1.4))
    grad = grad.resize((W, UST_H))
    karanlik = Image.new("RGB", (W, UST_H), NAVY)

    lg_kucuk = logo(70)
    lg_buyuk = logo(260)
    marka = chip("HC MEDYA HABERCİLİK", f_marka, NAVY, WHITE, pad=(0, 0))
    marka = Image.new("RGBA", marka.size, (0, 0, 0, 0))
    ImageDraw.Draw(marka).text((0, 0), "HC MEDYA HABERCİLİK", font=f_marka, fill=WHITE)

    c_ust = chip(ust_metin, f_chip, ust_renk, NAVY if gel else WHITE, pad=(26, 12))
    c_kat = chip(kat_metin, f_kat, AMBER if gel else NAVY, NAVY if gel else WHITE, pad=(20, 10))

    tick_metin = ("   •   ".join(["SON DAKİKA", "HC MEDYA HABERCİLİK", "@hcmedyahabercilik", "GÜNDEMİ TAKİP ET"]) + "   •   ")
    tick_w = int(f_tick.getlength(tick_metin))
    tick_img = Image.new("RGBA", (tick_w * 3, 70), (0, 0, 0, 0))
    td = ImageDraw.Draw(tick_img)
    for k in range(3):
        td.text((k * tick_w, 10), tick_metin, font=f_tick, fill=WHITE)

    PANEL_Y = 640 if foto else 560
    oy_bas = PANEL_Y + 120 + len(bas_sat) * lh + 34 + 44
    sigan = max(1, (ALT - oy_bas) // 62)
    if len(ozet_sat) > sigan:
        ozet_sat = ozet_sat[:sigan]
        son = ozet_sat[-1]
        while son and f_ozet.getlength(son + '…') > TW:
            son = son.rsplit(' ', 1)[0] if ' ' in son else son[:-1]
        ozet_sat[-1] = son.rstrip(',;:') + '…'
    etiket_w = int(f_tick.getlength(ust_metin)) + 100
    OUTRO_T = 12.4
    n_kare = int(SURE * FPS)

    muzik = muzik_sec(seed)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if muzik:
        cmd += ["-stream_loop", "-1", "-i", muzik,
                "-filter_complex", f"[1:a]atrim=0:{SURE},afade=t=in:d=0.8,afade=t=out:st={SURE-1.5}:d=1.5,volume=0.55[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-map", "0:v", "-map", "1:a"]
    cmd += ["-t", str(SURE), "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-movflags", "+faststart", cikti]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    for i in range(n_kare):
        t = i / FPS
        kare = Image.new("RGB", (W, H), LIGHT)

        # --- ust bolum: foto (Ken Burns) ya da desenli lacivert ---
        if foto:
            z = 1.0 + 0.12 * (t / SURE)
            fw, fh = int(W * z), int(UST_H * z)
            kx = int((foto.width - fw) * (0.5 + 0.25 * math.sin(t / SURE * math.pi)))
            ky = int((foto.height - fh) * 0.5)
            parca = foto.crop((kx, ky, kx + fw, ky + fh)).resize((W, UST_H), Image.LANCZOS)
            parca = Image.composite(karanlik, parca, grad)
            kare.paste(parca, (0, 0))
        else:
            kaydir = int((t * 40) % 70)
            kare.paste(arka.crop((0, 0, W, UST_H)), (-kaydir, 0))
            kare.paste(arka.crop((0, 0, kaydir + 1, UST_H)), (W - kaydir - 1, 0))
            wx = int(80 - t * 35)
            kare.paste(wm, (wx, 360), wm)

        # --- alt beyaz panel (yukari kayarak gelir) ---
        pk = ease_out((t - 0.15) / 0.6)
        py = int(H - (H - PANEL_Y) * pk)
        d = ImageDraw.Draw(kare)
        d.rectangle([0, py, W, H], fill=LIGHT)
        d.rectangle([0, py, 14, H], fill=ust_renk)  # sol kirmizi serit
        d.rectangle([0, py - 8, W, py], fill=ust_renk)

        # --- ust etiket ve marka ---
        ek = ease_out((t - 0.35) / 0.45)
        if ek > 0:
            x = int(-c_ust.width + (72 + c_ust.width) * ek)
            kare.paste(c_ust, (x, 150), c_ust)
            nabiz = 0.5 + 0.5 * math.sin(t * 6)
            r = int(9 + 4 * nabiz)
            cx = x + c_ust.width + 26
            d.ellipse([cx - r, 150 + c_ust.height // 2 - r, cx + r, 150 + c_ust.height // 2 + r], fill=ust_renk)
        mk = ease_out((t - 0.5) / 0.5)
        if mk > 0:
            lg = lg_kucuk.copy()
            lg.putalpha(lg.getchannel("A").point(lambda a: int(a * mk)))
            kare.paste(lg, (W - 72 - lg.width, 140), lg)

        # --- kategori + tarih ---
        kk = ease_out((t - 0.8) / 0.4)
        if kk > 0 and t < OUTRO_T + 0.6:
            kare.paste(c_kat, (72, int(PANEL_Y + 36 + (1 - kk) * 30)), c_kat)
            if tarih:
                tx = 72 + c_kat.width + 28
                tt = tarih if tx + f_tarih.getlength(tarih) <= W - 220 else tarih.split('·')[-1].strip()
                d.text((tx, PANEL_Y + 46 + (1 - kk) * 30), tt, font=f_tarih, fill=MUTED)

        # --- baslik: satir satir yukari kayarak ---
        by = PANEL_Y + 120
        for j, s in enumerate(bas_sat):
            sk = ease_out((t - 1.0 - j * 0.22) / 0.5)
            if sk <= 0:
                continue
            katman = Image.new("RGBA", (W, lh + 20), (0, 0, 0, 0))
            ImageDraw.Draw(katman).text((72, 0), s, font=f_b, fill=NAVY + (int(255 * sk),))
            kare.paste(katman, (0, int(by + j * lh + (1 - sk) * 40)), katman)
        # vurgu cizgisi
        cizgi_k = ease_out((t - 1.0 - len(bas_sat) * 0.22) / 0.5)
        oy = by + len(bas_sat) * lh + 34
        if cizgi_k > 0:
            d.rectangle([72, oy, 72 + int(160 * cizgi_k), oy + 8], fill=ust_renk)

        # --- ozet: satir satir ---
        oy += 44
        bas_ozet = 1.0 + len(bas_sat) * 0.22 + 0.9
        for j, s in enumerate(ozet_sat):
            sk = ease_out((t - bas_ozet - j * 0.45) / 0.45)
            if sk <= 0:
                continue
            katman = Image.new("RGBA", (W, 66), (0, 0, 0, 0))
            ImageDraw.Draw(katman).text((72, 0), s, font=f_ozet, fill=GRAY + (int(255 * sk),))
            kare.paste(katman, (int((1 - sk) * 30), oy + j * 62), katman)

        # --- kayan alt bant (Instagram'in kirptigi kenarlarin ve hesap adinin ustunde) ---
        bk = ease_out((t - 0.6) / 0.5)
        if bk > 0 and py < TICK_Y:
            d.rectangle([0, TICK_Y, W, TICK_Y + 76], fill=NAVY)
            d.rectangle([0, TICK_Y, etiket_w, TICK_Y + 76], fill=ust_renk)
            d.text((72, TICK_Y + 14), ust_metin, font=f_tick, fill=NAVY if gel else WHITE)
            off = int((t * 160) % tick_w)
            band = tick_img.crop((off, 0, off + W - etiket_w - 16, 70))
            kare.paste(band, (etiket_w + 16, TICK_Y + 4), band)

        # --- ilerleme cubugu ---
        d.rectangle([0, 0, int(W * t / SURE), 8], fill=ust_renk)

        # --- kapanis ---
        ok = ease_in_out((t - OUTRO_T) / 0.7)
        if ok > 0:
            perde = Image.new("RGB", (W, H), NAVY)
            pd = ImageDraw.Draw(perde)
            for q in range(-H, W, 90):
                pd.line([(q, H), (q + H, 0)], fill=NAVY2, width=20)
            kare = Image.blend(kare, perde, ok)
            ik = ease_out((t - OUTRO_T - 0.4) / 0.6)
            if ik > 0:
                lg = lg_buyuk.copy()
                lg.putalpha(lg.getchannel("A").point(lambda a: int(a * ik)))
                s = 0.85 + 0.15 * ik
                lg = lg.resize((int(lg.width * s), int(lg.height * s)), Image.LANCZOS)
                kare.paste(lg, ((W - lg.width) // 2, 520 - lg.height // 2), lg)
                d2 = ImageDraw.Draw(kare)
                y1 = 740
                for metin, f, renk in (("HC MEDYA HABERCİLİK", f_outro1, WHITE),
                                       ("Gündemi kaçırmamak için takip et", f_outro2, MUTED),
                                       ("@hcmedyahabercilik", f_outro2, AMBER)):
                    a = int(255 * ik)
                    katman = Image.new("RGBA", (W, 130), (0, 0, 0, 0))
                    ImageDraw.Draw(katman).text(((W - f.getlength(metin)) / 2, 0), metin, font=f, fill=renk + (a,))
                    kare.paste(katman, (0, int(y1 + (1 - ik) * 30)), katman)
                    y1 += 130 if f is f_outro1 else 80
                d2.rectangle([(W - 200) // 2, 1090, (W + 200) // 2, 1098], fill=RED)

        p.stdin.write(kare.tobytes())

    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit("ffmpeg hatasi")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    with open(a.json, encoding="utf-8") as f:
        uret(json.load(f), a.out)
    print("tamam:", a.out)
