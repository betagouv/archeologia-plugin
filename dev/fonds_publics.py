"""Écrit le catalogue public des fonds de carte (`data/fonds_publics/fonds.json`) et ses vignettes.

Les fonds sont des couches WMTS **sans clé** de la Géoplateforme : ce catalogue ne porte donc aucun
secret et part dans le ZIP. Format, style et niveaux de zoom viennent du GetCapabilities ; la liste
ci-dessous ne fixe que ce qu'un humain décide (titre, époque, ordre, repère, zone d'un fond local).

    python dev/fonds_publics.py            # réécrit fonds.json + vignettes (Pillow requis)

Liste validée par l'utilisateur le 2026-11-11. L'ordre de la liste est l'ordre d'affichage.
"""
from __future__ import annotations

import io
import json
import math
import re
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "data" / "fonds_publics"
SERVICE = "https://data.geopf.fr/wmts"
VIGNETTE_PX = 128
ICI = (7.03, 48.86)       # Fénétrange : là où les vignettes sont prises, sauf mention contraire
LIEUX = {ICI: "Fénétrange, Moselle", (2.13, 48.80): "Versailles, Yvelines", (5.39, 49.20): "Verdun, Meuse",
         (-1.68, 48.11): "Rennes, Ille-et-Vilaine", (2.67, 48.42): "forêt de Fontainebleau, Seine-et-Marne"}
APERCU_PX = 512

# (id, couche IGN, titre, époque affichée, début, fin, source, options)
# fin None = jusqu'à aujourd'hui ; début None = sans date. options : repere, zone, vignette_a (lon, lat).
FONDS = [
    ("cassini", "BNF-IGNF_GEOGRAPHICALGRIDSYSTEMS.CASSINI", "Carte de Cassini", "1756-1815", 1756, 1815, "BnF, IGN",
     {"theme": "Cartes anciennes"}),
    ("etat_major_10", "GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR10", "État-major détaillé", "1818-1824", 1818, 1824, "IGN",
     {"theme": "Cartes anciennes", "zone": "environs de Paris", "vignette_a": (2.13, 48.8)}),
    ("etat_major", "GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR40", "Carte de l'état-major", "1820-1866", 1820, 1866, "IGN",
     {"theme": "Cartes anciennes"}),
    ("forets_anciennes", "IGNF_FORETS-ANCIENNES", "Forêts anciennes", "1820-1866", 1820, 1866, "IGN",
     {"theme": "Cartes anciennes", "repere": True, "vignette_a": (2.67, 48.42)}),
    ("verdun_1916", "GEOGRAPHICALGRIDSYSTEMS.EDUGEO.Positions_20K_avr1916", "Front de Verdun", "avril 1916", 1916, 1916, "IGN",
     {"theme": "Cartes anciennes", "zone": "Meuse", "vignette_a": (5.39, 49.2)}),
    ("carte_1950", "GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN50.1950", "Carte de 1950", "vers 1950", 1947, 1953, "IGN",
     {"theme": "Cartes anciennes"}),
    ("photos_1950", "ORTHOIMAGERY.ORTHOPHOTOS.1950-1965", "Photos aériennes", "1950-1965", 1950, 1965, "IGN",
     {"theme": "Photos aériennes"}),
    ("photos_1965", "ORTHOIMAGERY.ORTHOPHOTOS.1965-1980", "Photos aériennes", "1965-1980", 1965, 1980, "IGN",
     {"theme": "Photos aériennes"}),
    ("photos_1980", "ORTHOIMAGERY.ORTHOPHOTOS.1980-1995", "Photos aériennes", "1980-1995", 1980, 1995, "IGN",
     {"theme": "Photos aériennes", "vignette_a": (-1.68, 48.11)}),
    ("lidar_classes", "IGNF_LIDAR-HD_CLASS", "Classes du nuage LiDAR HD", "2020-2025", 2020, 2025, "IGN",
     {"theme": "Relief, sol et géologie"}),
    ("photos", "ORTHOIMAGERY.ORTHOPHOTOS", "Photos aériennes", "aujourd'hui", 2020, None, "IGN",
     {"theme": "Photos aériennes"}),
    ("photos_irc", "ORTHOIMAGERY.ORTHOPHOTOS.IRC", "Photos infrarouge couleur", "aujourd'hui", 2020, None, "IGN",
     {"theme": "Photos aériennes"}),
    ("plan_ign", "GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", "Plan IGN", "aujourd'hui", 2020, None, "IGN",
     {"theme": "Relief, sol et géologie"}),
    ("cadastre", "CADASTRALPARCELS.PARCELLAIRE_EXPRESS", "Parcelles cadastrales", "aujourd'hui", 2020, None, "IGN, DGFiP",
     {"theme": "Relief, sol et géologie", "repere": True}),
    ("geologie", "BRGM_SCAN_D_GEOL50", "Carte géologique 1:50 000", "sans date", None, None, "BRGM",
     {"theme": "Relief, sol et géologie"}),
    # ── 2026-11-13 : les 40 images « à l'essai » validées par l'utilisateur ──
    ("verdun_douaumont", "GEOGRAPHICALGRIDSYSTEMS.EDUGEO.Douaumont1916", "Douaumont et ses environs", "avril 1916", 1916, 1916, "IGN",
     {"theme": "Cartes anciennes", "vignette_a": (5.439, 49.2165), "lieu": "Fort de Douaumont, Meuse", "zone": "Meuse"}),
    ("verdun_fort_douaumont", "GEOGRAPHICALGRIDSYSTEMS.DOUAUMONT_FORT_positions_5K_18mai1916", "Fort de Douaumont", "mai 1916", 1916, 1916, "IGN",
     {"theme": "Cartes anciennes", "vignette_a": (5.4395, 49.217), "lieu": "Fort de Douaumont, Meuse", "z": 16, "zone": "Meuse"}),
    ("verdun_mort_homme", "GEOGRAPHICALGRIDSYSTEMS.EDUGEO.Le-Mort-Homme-et-ses-environs-avril-1916", "Le Mort-Homme et ses environs", "avril 1916", 1916, 1916, "IGN",
     {"theme": "Cartes anciennes", "vignette_a": (5.253, 49.229), "lieu": "Le Mort-Homme (cote 295), Meuse", "zone": "Meuse"}),
    ("verdun_defenses", "GEOGRAPHICALGRIDSYSTEMS.EDUGEO.VERDUN_NORD_organisations_defensives_20K", "Verdun nord : défenses", "février 1916", 1916, 1916, "IGN",
     {"theme": "Cartes anciennes", "vignette_a": (5.42, 49.281), "lieu": "Bois le Comte, au sud de Flabas, Meuse", "z": 13, "zone": "Meuse"}),
    ("verdun_fronts", "GEOGRAPHICALGRIDSYSTEMS.EDUGEO.VERDUN_NORD_fronts_francais_20K", "Verdun nord : fronts français", "février 1916", 1916, 1916, "IGN",
     {"theme": "Cartes anciennes", "vignette_a": (5.425, 49.225), "lieu": "Entre Louvemont et Douaumont, Meuse", "z": 13, "zone": "Meuse"}),
    ("verdun_offensives", "GEOGRAPHICALGRIDSYSTEMS.VERDUN_ENVIRONS_NORD_fronts_offensves_50K", "Verdun : offensives", "1916-1917", 1916, 1917, "IGN",
     {"theme": "Cartes anciennes", "vignette_a": (5.4, 49.22), "lieu": "Rive droite de la Meuse, de Vacherauville à Douaumont, Meuse", "z": 12, "zone": "Meuse"}),
    ("terrier_corse_1", "GEOGRAPHICALGRIDSYSTEMS.TERRIER_V1", "Plan terrier de Corse (version 1)", "1770-1795", 1770, 1795, "IGN",
     {"theme": "Cartes anciennes", "vignette_a": (9.44, 42.7), "lieu": "Cardo et Bastia, Haute-Corse", "z": 14, "zone": "Corse"}),
    ("terrier_corse_2", "GEOGRAPHICALGRIDSYSTEMS.TERRIER_V2", "Plan terrier de Corse (version 2)", "1770-1795", 1770, 1795, "IGN",
     {"theme": "Cartes anciennes", "vignette_a": (9.44, 42.7), "lieu": "Cardo et Bastia, Haute-Corse", "z": 14, "zone": "Corse"}),
    ("paris_1906", "GEOGRAPHICALGRIDSYSTEMS.1900TYPEMAPS", "Carte des environs de Paris", "1906", 1906, 1906, "IGN",
     {"theme": "Cartes anciennes", "vignette_a": (2.13, 48.8), "lieu": "Versailles, Yvelines", "z": 13, "zone": "environs de Paris"}),
    ("carte_littorale", "GEOGRAPHICALGRIDSYSTEMS.COASTALMAPS", "Carte littorale", "aujourd'hui", 2020, None, "SHOM, IGN",
     {"theme": "Relief, sol et géologie", "vignette_a": (-2.03, 48.65), "lieu": "Rade de Saint-Malo, Ille-et-Vilaine", "z": 13}),
    ("carte_allemande_voies_ferrees_1917", "lbwgs1:LBWGS1_M_640_Nr_11863", "Carte allemande des voies ferrées", "octobre 1917", 1917, 1917, "Landesarchiv Baden-Württemberg",
     {"theme": "Cartes anciennes", "vignette_a": (7.05, 48.47), "lieu": "Vallée de la Plaine, Vosges", "z": 12, "wms": "https://www.datagrandest.fr/geoserver/ows", "format": "image/jpeg", "zone": "Alsace et Vosges", "emprise": (6.5858, 47.9489, 8.2038, 48.8488)}),
    ("carte_allemande_haut_rhin_1915", "lbwgs1:LBWGS1_M_640_Nr_11877", "Carte allemande du front de Haute-Alsace", "mai 1915", 1915, 1915, "Landesarchiv Baden-Württemberg",
     {"theme": "Cartes anciennes", "vignette_a": (7.15, 47.9), "lieu": "Hartmannswillerkopf et Guebwiller, Haut-Rhin", "z": 12, "wms": "https://www.datagrandest.fr/geoserver/ows", "format": "image/jpeg", "zone": "Haute-Alsace", "emprise": (6.683, 47.3043, 8.0034, 48.6028)}),
    ("carte_allemande_1918", "lbwgs1:LBWGS1_M_640_Nr_11871_1", "Carte allemande du front de Lorraine et des Vosges", "mai 1918", 1918, 1918, "Landesarchiv Baden-Württemberg",
     {"theme": "Cartes anciennes", "vignette_a": (6.93, 48.48), "lieu": "Badonviller, Meurthe-et-Moselle", "z": 12, "wms": "https://www.datagrandest.fr/geoserver/ows", "format": "image/jpeg", "zone": "Lorraine et Vosges", "emprise": (6.3555, 47.9763, 7.9253, 48.8454)}),
    ("photos_2000", "ORTHOIMAGERY.ORTHOPHOTOS2000-2005", "Photos aériennes", "2000-2005", 2000, 2005, "IGN",
     {"theme": "Photos aériennes", "vignette_a": (7.03, 48.86), "lieu": "Fénétrange, Moselle"}),
    ("photos_2006", "ORTHOIMAGERY.ORTHOPHOTOS2006-2010", "Photos aériennes", "2006-2010", 2006, 2010, "IGN",
     {"theme": "Photos aériennes", "vignette_a": (7.03, 48.86), "lieu": "Fénétrange, Moselle"}),
    ("photos_2011", "ORTHOIMAGERY.ORTHOPHOTOS2011-2015", "Photos aériennes", "2011-2015", 2011, 2015, "IGN",
     {"theme": "Photos aériennes", "vignette_a": (7.03, 48.86), "lieu": "Fénétrange, Moselle"}),
    ("photos_2016", "ORTHOIMAGERY.ORTHOPHOTOS2016-2020", "Photos aériennes", "2016-2020", 2016, 2020, "IGN",
     {"theme": "Photos aériennes", "vignette_a": (7.03, 48.86), "lieu": "Fénétrange, Moselle"}),
    ("photos_2021", "ORTHOIMAGERY.ORTHOPHOTOS2021-2023", "Photos aériennes", "2021-2023", 2021, 2023, "IGN",
     {"theme": "Photos aériennes", "vignette_a": (7.03, 48.86), "lieu": "Fénétrange, Moselle"}),
    ("photos_calvados_1947", "orthophoto_1947_calvados", "Photos aériennes du Calvados", "1947", 1947, 1947, "IGN",
     {"theme": "Photos aériennes", "vignette_a": (-0.75, 49.25), "lieu": "Bocage au sud-ouest de Bayeux, Calvados", "zone": "Calvados"}),
    ("photos_calvados_1955", "orthophoto_1955_calvados", "Photos aériennes du Calvados", "1955", 1955, 1955, "IGN",
     {"theme": "Photos aériennes", "vignette_a": (-0.75, 49.25), "lieu": "Bocage au sud-ouest de Bayeux, Calvados", "zone": "Calvados"}),
    ("photos_calvados_1972", "orthophoto_1972_calvados", "Photos aériennes du Calvados", "1972", 1972, 1972, "IGN",
     {"theme": "Photos aériennes", "vignette_a": (-0.75, 49.25), "lieu": "Bocage au sud-ouest de Bayeux, Calvados", "zone": "Calvados"}),
    ("photos_calvados_1984", "orthophoto_1984_calvados", "Photos aériennes du Calvados", "1984", 1984, 1984, "IGN",
     {"theme": "Photos aériennes", "vignette_a": (-0.75, 49.25), "lieu": "Bocage au sud-ouest de Bayeux, Calvados", "zone": "Calvados"}),
    ("photos_calvados_1991", "orthophoto_1991_calvados", "Photos aériennes du Calvados", "1991", 1991, 1991, "IGN",
     {"theme": "Photos aériennes", "vignette_a": (-0.75, 49.25), "lieu": "Bocage au sud-ouest de Bayeux, Calvados", "zone": "Calvados"}),
    ("littoral_2000", "ORTHOIMAGERY.ORTHOPHOTOS.COAST2000", "Photos du littoral", "2000-2002", 2000, 2002, "IGN",
     {"theme": "Photos aériennes", "vignette_a": (-1.511, 48.636), "lieu": "Le Mont-Saint-Michel, Manche"}),
    ("strasbourg_photos_1964", "ems:EMS_Ortho_1964", "Strasbourg : photos aériennes", "1964", 1964, 1964, "Eurométropole de Strasbourg",
     {"theme": "Photos aériennes", "vignette_a": (7.7755, 48.575), "lieu": "Citadelle de Strasbourg, Bas-Rhin", "z": 16, "wms": "https://www.datagrandest.fr/geoserver/ows", "format": "image/jpeg", "zone": "Strasbourg", "emprise": (7.6191, 48.4756, 7.8755, 48.7047)}),
    ("lidar_ombre", "IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.SHADOW", "Relief LiDAR HD ombré de l'IGN", "2020-2026", 2020, 2026, "IGN",
     {"theme": "Relief, sol et géologie", "vignette_a": (7.03, 48.86), "lieu": "Fénétrange, Moselle"}),
    ("lidar_hauteur", "IGNF_LIDAR-HD_MNH_ELEVATION.ELEVATIONGRIDCOVERAGE.SHADOW", "Hauteurs LiDAR HD ombrées (végétation et bâti)", "2020-2026", 2020, 2026, "IGN",
     {"theme": "Relief, sol et géologie", "vignette_a": (7.03, 48.86), "lieu": "Fénétrange, Moselle"}),
    ("estompage", "IGNF_ELEVATION.ELEVATIONGRIDCOVERAGE.SHADOW", "Estompage du relief", "2010-2024", 2010, 2024, "IGN",
     {"theme": "Relief, sol et géologie", "vignette_a": (7.03, 48.86), "lieu": "Fénétrange, Moselle"}),
    ("courbes", "ELEVATION.CONTOUR.LINE", "Courbes de niveau", "2010-2024", 2010, 2024, "IGN",
     {"theme": "Relief, sol et géologie", "vignette_a": (7.03, 48.86), "lieu": "Fénétrange, Moselle", "repere": True, "legende_url": "https://data.geopf.fr/annexes/ressources/legendes/ELEVATION-CONTOUR-LINE-legend.png"}),
    ("ocsge_couverture", "OCSGE.COUVERTURE.2021-2023", "Occupation du sol : couverture", "2021-2023", 2021, 2023, "IGN",
     {"theme": "Relief, sol et géologie", "vignette_a": (7.03, 48.86), "lieu": "Fénétrange, Moselle", "z": 14, "legende_url": "https://data.geopf.fr/annexes/ressources/legendes/OCSGE.COUVERTURE-legend.png"}),
    ("ocsge_usage", "OCSGE.USAGE.2021-2023", "Occupation du sol : usage (OCS GE)", "2021-2023", 2021, 2023, "IGN",
     {"theme": "Relief, sol et géologie", "vignette_a": (7.03, 48.86), "lieu": "Fénétrange, Moselle", "z": 14, "legende_url": "https://data.geopf.fr/annexes/ressources/legendes/ocsge/OCSGE_USAGE.png"}),
    ("cosia", "IGNF_COSIA_2021-2023", "Couverture du sol par IA (CoSIA)", "2021-2023", 2021, 2023, "IGN",
     {"theme": "Relief, sol et géologie", "vignette_a": (7.03, 48.86), "lieu": "Fénétrange, Moselle", "legende_url": "https://data.geopf.fr/annexes/ressources/legendes/CoSIA-legend.png"}),
    ("geologie_harmonisee", "SCAN_H_GEOL50", "Carte géologique harmonisée", "sans date", None, None, "BRGM",
     {"theme": "Relief, sol et géologie", "vignette_a": (7.03, 48.86), "lieu": "Fénétrange, Moselle", "z": 14, "wms": "https://geoservices.brgm.fr/geologie", "format": "image/png"}),
    ("inrap", "INRAP-ARCHEOPREV_BDD-POI_WLD_WM", "Sélection de fouilles de l'INRAP", "relevé de 2014", 2014, 2014, "INRAP",
     {"theme": "Relief, sol et géologie", "vignette_a": (6.175, 49.108), "lieu": "Metz, Moselle", "z": 9, "repere": True, "wms": "https://data.geopf.fr/wms-v/ows", "format": "image/png", "legende_url": "https://data.geopf.fr/wms-v/ows?service=WMS&version=1.3.0&request=GetLegendGraphic&format=image/png&width=20&height=20&layer=INRAP-ARCHEOPREV_BDD-POI_WLD_WM"}),
]


def _tuile(lon: float, lat: float, z: int) -> tuple:
    n = 2 ** z
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


def bbox_3857(col: int, rang: int, z: int, n: int = 1) -> tuple:
    """Emprise Web Mercator de ``n`` × ``n`` tuiles à partir de la tuile (col, rang) du zoom ``z``."""
    tour = 2 * math.pi * 6378137
    cote = tour / 2 ** z
    x0, y1 = -tour / 2 + col * cote, tour / 2 - rang * cote
    return x0, y1 - n * cote, x0 + n * cote, y1


def url_wms(wms: str, couche: str, fmt: str, bbox: tuple, px: int) -> str:
    """GetMap d'un service WMS d'un autre producteur (BRGM, DataGrandEst…), en Web Mercator."""
    return (f"{wms}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS={couche}&STYLES=&CRS=EPSG:3857"
            f"&BBOX={','.join(f'{v:.2f}' for v in bbox)}&WIDTH={px}&HEIGHT={px}&FORMAT={fmt}&TRANSPARENT=TRUE")


def _lire(url: str, delai: int = 90) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "QGIS"}), timeout=delai).read()


def _sur_blanc(brut: bytes):
    from PIL import Image

    img = Image.open(io.BytesIO(brut)).convert("RGBA")
    blanc = Image.new("RGBA", img.size, "white")
    blanc.alpha_composite(img)
    return blanc.convert("RGB")


def main(argv=None) -> int:
    import argparse

    from PIL import Image

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refaire", action="store_true", help="retélécharge aussi les images déjà présentes")
    args = ap.parse_args(argv)

    xml = _lire(f"{SERVICE}?SERVICE=WMTS&REQUEST=GetCapabilities", 180).decode("utf-8")
    decrit = {}
    for bloc in re.findall(r"<Layer>(.*?)</Layer>", xml, flags=re.S):
        ident = re.search(r"<ows:Identifier>(.*?)<", bloc).group(1)
        style = re.search(r"<Style[^>]*>.*?<ows:Identifier>(.*?)<", bloc, flags=re.S)
        coins = re.search(r"<ows:LowerCorner>(.*?)</ows:LowerCorner>\s*<ows:UpperCorner>(.*?)<", bloc)
        zooms = [int(z) for z in re.findall(r"<TileMatrix>(\d+)</TileMatrix>", bloc)]
        legende = re.search(r'<LegendURL[^>]*xlink:href="([^"]+)"', bloc)
        decrit[ident] = (re.search(r"<Format>(.*?)<", bloc).group(1), style.group(1) if style else "normal",
                         min(zooms), max(zooms), coins.groups() if coins else None,
                         legende.group(1) if legende else "")

    (SORTIE / "vignettes").mkdir(parents=True, exist_ok=True)
    (SORTIE / "legendes").mkdir(parents=True, exist_ok=True)
    (SORTIE / "apercus").mkdir(parents=True, exist_ok=True)
    fonds = []
    for ident, couche, titre, epoque, debut, fin, source, opt in FONDS:
        wms = opt.get("wms", "")
        if wms:      # service d'un autre producteur : ni grille de tuiles ni niveaux de zoom annoncés
            fmt, style, zmin, zmax, coins, url_legende = opt.get("format", "image/png"), "normal", 0, 19, None, ""
        else:
            fmt, style, zmin, zmax, coins, url_legende = decrit[couche]
        url_legende = opt.get("legende_url", url_legende)
        lieu = opt.get("vignette_a", ICI)
        z = opt.get("z", min(15, zmax))
        col, rang = _tuile(*lieu, z)

        def image(n: int, px: int, _c=col, _r=rang, _z=z, _wms=wms, _couche=couche, _fmt=fmt, _style=style):
            """``n`` × ``n`` tuiles autour du lieu, sur fond blanc, en ``px`` pixels."""
            if _wms:
                return _sur_blanc(_lire(url_wms(_wms, _couche, _fmt, bbox_3857(_c, _r, _z, n), 256 * n))).resize(
                    (px, px), Image.LANCZOS)
            mosaique = Image.new("RGB", (256 * n, 256 * n), "white")
            for dx in range(n):
                for dy in range(n):
                    u = (f"{SERVICE}?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER={_couche}&STYLE={_style}"
                         f"&FORMAT={_fmt}&TILEMATRIXSET=PM&TILEMATRIX={_z}&TILEROW={_r + dy}&TILECOL={_c + dx}")
                    try:
                        mosaique.paste(_sur_blanc(_lire(u, 60)), (dx * 256, dy * 256))
                    except OSError:
                        if n == 1:
                            raise
            return mosaique.resize((px, px), Image.LANCZOS)

        vignette, apercu = f"vignettes/{ident}.jpg", f"apercus/{ident}.jpg"
        if args.refaire or not (SORTIE / vignette).is_file():
            image(1, VIGNETTE_PX).save(SORTIE / vignette, quality=82)
        if args.refaire or not (SORTIE / apercu).is_file():      # aperçu de la fiche : 2 × 2 tuiles au même endroit
            image(2, APERCU_PX).save(SORTIE / apercu, quality=85)
        fond = {"id": ident, "couche": couche, "titre": titre, "epoque": epoque, "debut": debut, "fin": fin,
                "format": fmt, "style": style, "zmin": zmin, "zmax": zmax,
                # Un service WMS n'annonce pas sa finesse : 0 = non affichée.
                "detail_m": 0 if wms else round(156543.03 * math.cos(math.radians(47)) / 2 ** zmax, 1),
                "repere": bool(opt.get("repere")), "vignette": vignette, "apercu": apercu,
                "lieu_apercu": opt.get("lieu") or LIEUX[lieu], "source": source, "theme": opt["theme"]}
        if wms:
            fond["wms"] = wms
        # Légende officielle, livrée avec le plugin : une couche ouverte en tuiles directes n'en porte pas.
        # Beaucoup de fonds n'ont que l'image générique « LEGEND.jpg » de la Géoplateforme : rien à montrer.
        if url_legende and not url_legende.endswith("/LEGEND.jpg"):
            chemin = f"legendes/{ident}.png"
            if args.refaire or not (SORTIE / chemin).is_file():
                try:
                    leg = Image.open(io.BytesIO(_lire(url_legende, 120))).convert("RGB")
                    leg.quantize(colors=128, method=Image.Quantize.MEDIANCUT).save(SORTIE / chemin, optimize=True)
                except OSError as exc:      # un PDF, une adresse morte : pas de légende plutôt qu'un arrêt
                    print("  légende illisible :", url_legende, type(exc).__name__, flush=True)
            if (SORTIE / chemin).is_file():
                fond["legende"] = chemin
        if "zone" in opt:      # fond local : son emprise (lon/lat) borne l'offre et la couche
            fond["zone"] = opt["zone"]
            if "emprise" in opt:
                fond["emprise"] = list(opt["emprise"])
            else:
                bas, haut = coins
                fond["emprise"] = [float(v) for v in (bas.split() + haut.split())]
        fonds.append(fond)
        print(ident, fmt, style, zmin, zmax, fond["detail_m"], flush=True)

    # Les vecteurs (« objets ») sont écrits par dev/fonds_objets.py : on les garde tels quels.
    try:
        anciens = json.loads((SORTIE / "fonds.json").read_text(encoding="utf-8")).get("fonds") or []
    except (OSError, ValueError):
        anciens = []
    objets = [f for f in anciens if f.get("typename")]
    dates = sorted((f for f in fonds if f["debut"] is not None), key=lambda f: f["debut"])     # tri stable
    fonds = dates + [f for f in fonds if f["debut"] is None] + objets      # les images, puis les vecteurs
    (SORTIE / "fonds.json").write_text(
        json.dumps({"service": SERVICE, "fonds": fonds}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(len(fonds), "fonds écrits dans", SORTIE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
