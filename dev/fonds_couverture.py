"""Mesure la couverture réelle de chaque fond public sur la France → `data/fonds_publics/couverture.json`.

La carte de France d'une fiche de fond montre où le fond a **vraiment** une image : certains sont
incomplets (photos 1980-1995), locaux (front de Verdun) ou n'existaient pas partout à l'époque
(Cassini sans la Corse ni la Savoie). On demande une tuile par case de la grille Web Mercator au
zoom `ZOOM` (≈ 25 km), pour les cases dont le centre tombe en France : couverte si le serveur
répond une image qui n'est ni entièrement transparente ni d'une seule couleur ; une case vide est
redemandée plus finement (zoom `ZOOM_FIN`) en son centre avant d'être déclarée vide.

    python dev/fonds_couverture.py              # réseau, quelques milliers de requêtes par fond (Pillow requis)
    python dev/fonds_couverture.py --manquants  # seulement les fonds qui n'ont pas encore de couverture

Le contour de la France est celui de `data/zones_corpus.json` (Natural Earth, déjà livré).
"""
from __future__ import annotations

import io
import json
import math
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
from src.app.services import fonds_publics as fp  # noqa: E402

ZOOM = 10
ZOOM_FIN = 14


def fp_tuile(lon: float, lat: float, zoom: int):
    n = 2 ** zoom
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
SORTIE = RACINE / fp.CATALOGUE.parent / "couverture.json"


def _dans(anneaux, lon: float, lat: float) -> bool:
    """Point dans l'un des anneaux (lancer de rayon)."""
    for a in anneaux:
        dedans = False
        for (x1, y1), (x2, y2) in zip(a, a[1:] + a[:1]):
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                dedans = not dedans
        if dedans:
            return True
    return False


def _couverte(url: str) -> bool:
    from PIL import Image

    for _essai in range(3):
        try:
            brut = urllib.request.urlopen(url, timeout=40).read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return False
            continue
        except OSError:
            continue
        try:
            bandes = Image.open(io.BytesIO(brut)).convert("RGBA").getextrema()
        except OSError:
            return False                      # un message d'erreur du service à la place d'une image
        if bandes[3][1] == 0:
            return False                      # entièrement transparente
        # Une image unie n'est pas une image du fond : Cassini répond du blanc sur la Corse.
        return any(mini != maxi for mini, maxi in bandes[:3])
    return False


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seulement", nargs="*", default=[], help="ne mesure que ces fonds, garde les autres")
    ap.add_argument("--manquants", action="store_true", help="ne mesure que les fonds sans couverture")
    args = ap.parse_args(argv)
    service, fonds = fp.charger(RACINE / fp.CATALOGUE)
    contours = json.loads((RACINE / "data" / "zones_corpus.json").read_text(encoding="utf-8"))["contours"]["france"]
    anneaux = [[(float(p[0]), float(p[1])) for p in a] for a in contours]
    n = 2 ** ZOOM
    lon0, lat0, lon1, lat1 = fp.FRANCE
    x0 = int((lon0 + 180) / 360 * n)
    x1 = int((lon1 + 180) / 360 * n)

    def rang(lat: float) -> int:
        return int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

    y0, y1 = rang(lat1), rang(lat0)
    cases = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
             if _dans(anneaux, *fp.centre_case(ZOOM, x, y))]
    print(len(cases), "cases en France au zoom", ZOOM, "| colonnes", x0, "à", x1, "| rangées", y0, "à", y1)

    sortie = {"zoom": ZOOM, "x0": x0, "y0": y0, "colonnes": x1 - x0 + 1, "rangees": y1 - y0 + 1,
              "cases_france": len(cases), "fonds": {}}
    try:      # les vecteurs ne se sondent pas par tuiles : leur couverture est écrite par dev/fonds_objets.py
        gardes = json.loads(SORTIE.read_text(encoding="utf-8")).get("fonds") or {}
    except (OSError, ValueError):
        gardes = {}
    from dev.fonds_publics import bbox_3857, url_wms

    def url(fond, case, zoom=ZOOM):
        """La tuile de la case, ou — service WMS d'un autre producteur — l'image de la même emprise."""
        if fond.wms:
            return url_wms(fond.wms, fond.couche, fond.format, bbox_3857(case[0], case[1], zoom), 256)
        return (f"{service}?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER={fond.couche}&STYLE={fond.style}"
                f"&FORMAT={fond.format}&TILEMATRIXSET=PM&TILEMATRIX={zoom}&TILEROW={case[1]}&TILECOL={case[0]}")

    for fond in fonds:
        if fond.objets or (args.seulement and fond.id not in args.seulement) or (
                args.manquants and fond.id in gardes):
            if fond.id in gardes:
                sortie["fonds"][fond.id] = gardes[fond.id]
            continue
        z = max(fond.zmin, min(fond.zmax, ZOOM))
        assert z == ZOOM, f"{fond.id} : zoom {ZOOM} non servi"
        # Un fond local n'est sondé que sur son emprise : ailleurs, il n'y a rien par construction.
        a_sonder = [c for c in cases if fp.couvre(fond, fp.bornes_case(ZOOM, *c))]
        fils = 6 if fond.wms else 24             # un service régional ne tient pas 24 demandes à la fois
        with ThreadPoolExecutor(fils) as ex:
            res = list(ex.map(lambda c, f=fond: _couverte(url(f, c)), a_sonder))
        oui = {c for c, r in zip(a_sonder, res) if r}
        # Seconde passe sur les cases trouvées vides : à ce zoom, un fond en traits fins (cadastre)
        # peut ne rien dessiner alors qu'il existe. On redemande une tuile fine au centre de la case.
        fin = min(fond.zmax, ZOOM_FIN)
        vides = [c for c in a_sonder if c not in oui]

        def fine(c, f=fond, fin=fin):
            return _couverte(url(f, fp_tuile(*fp.centre_case(ZOOM, *c), fin), fin))

        with ThreadPoolExecutor(fils) as ex:
            oui |= {c for c, r in zip(vides, ex.map(fine, vides)) if r}
        lignes = ["".join("1" if (x, y) in oui else "0" for x in range(x0, x1 + 1)) for y in range(y0, y1 + 1)]
        sortie["fonds"][fond.id] = {"cases": len(oui), "lignes": lignes}
        print(f"{fond.id:18s} {len(oui):4d} / {len(cases)}  ({100 * len(oui) / len(cases):.0f} %)", flush=True)
        # Écrit après chaque fond : une mesure interrompue reprend avec --manquants.
        SORTIE.write_text(json.dumps({**sortie, "fonds": {**gardes, **sortie["fonds"]}}, ensure_ascii=False, indent=0)
                          + "\n", encoding="utf-8")
    SORTIE.write_text(json.dumps(sortie, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
