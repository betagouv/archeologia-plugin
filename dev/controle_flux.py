# -*- coding: utf-8 -*-
"""Contrôle des flux de l'onglet « Catalogue des flux », hors écran (2026-11-18).

Chaque source se construit **par le code du plugin** (jamais d'URL recopiée ici), puis se rend en
vignette sur une emprise où elle doit avoir des données :

* catalogue des indices (``data/demo_catalogue`` fusionné avec ``data/local_catalogue``, comme
  ``VisualisationTab.reload_catalogue``) : ``_sonder_flux`` pour un flux, ``QgsRasterLayer(..., "gdal")``,
  ``_sans_etirement``, emprise du catalogue ; rendu sur l'emprise entière (ce que montre le premier
  zoom) **et** sur 2 km au centre ;
* fonds publics (``fonds.json``) et sources à l'essai (``essais.json``) : ``FondsPage.ajouter_fonds`` ;
  une image se rend sur une case couverte de ``couverture.json`` (bornée à son emprise), un vecteur sur
  1,2 km autour d'un sommet du premier objet trouvé, filtre de dessin évalué sur le poste (sous le
  1:25 000 où il s'affiche) ; une couche valide sans géométrie (jamais dessinée) est KO ;
* contexte moderne (``CONTEXTE_MODERNE``) : ``couches_contexte`` puis ``ajouter_fonds`` par famille.

Une source KO est relancée une fois (panne passagère ou défaut). ⚠ Le catalogue local porte une clé
d'accès : toute chaîne écrite passe par ``_masque``. Sorties : ``<sortie>/verdicts.json`` (par source :
``ok`` vrai/faux/null = sans objet, ``preuve``, ``duree_s``, ``service``), ``controles.txt`` terminé par
``RESULTAT : OK|ECHEC``, une vignette PNG par source dans ``<sortie>/vignettes``.

    C:/OSGeo4W/bin/python-qgis.bat dev/controle_flux.py --sortie D:/brouillons/controle_flux/q3
    "C:/Program Files/QGIS 4.0.3/bin/python-qgis.bat" dev/controle_flux.py --sortie D:/brouillons/controle_flux/q4

``--seulement <motif>`` : les sources dont l'identifiant contient ce motif. À lancer sous les deux QGIS.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rendu_hors_ecran import RACINE, _app  # noqa: E402

VERDICTS: dict = {}
LOG = None
TAILLE = 256
FENETRE_OBJETS_M = 1200            # 256 px → ≈ 1:17 700, sous ECHELLE_MIN_OBJETS (25 000)
FENETRE_DETAIL_M = 2000
DELAI_RENDU_S = 60
FENETRAGE = (997900.0, 6746100.0)  # Fénétrange (Moselle), EPSG:2154 : lieu des aperçus du catalogue
_CLE = re.compile(r"(?i)((?:api)?key=)[^&\s\"'<>]+")


def _masque(texte) -> str:
    return _CLE.sub(r"\1***", str(texte))


def log(*parts):
    LOG.write(_masque(" ".join(str(p) for p in parts)) + "\n")
    LOG.flush()


# ---------------------------------------------------------------- rendu
class _Messages:
    """Messages du journal QGIS reçus pendant un contrôle (erreurs réseau, WFS, WMS)."""

    def __init__(self):
        from qgis.core import QgsApplication
        self.recus = []
        QgsApplication.messageLog().messageReceived.connect(self._recevoir)

    def _recevoir(self, message, tag, niveau):
        from qgis.core import Qgis
        if niveau in (Qgis.MessageLevel.Warning, Qgis.MessageLevel.Critical):
            self.recus.append(f"[{tag}] {message}")

    def vider(self):
        out, self.recus = self.recus, []
        return out


def _rendre(couche, rect, crs, png: Path):
    """``(image, erreurs, secondes)`` : rendu ``TAILLE``² de ``couche`` sur ``rect`` (dans ``crs``)."""
    from qgis.core import QgsMapRendererParallelJob, QgsMapSettings
    from qgis.PyQt.QtCore import QEventLoop, QSize, QTimer
    from qgis.PyQt.QtGui import QColor

    ms = QgsMapSettings()
    ms.setLayers([couche])
    ms.setDestinationCrs(crs)
    ms.setOutputSize(QSize(TAILLE, TAILLE))
    ms.setBackgroundColor(QColor(0, 0, 0, 0))
    ms.setExtent(rect)
    job = QgsMapRendererParallelJob(ms)
    boucle = QEventLoop()
    job.finished.connect(boucle.quit)
    minuterie = QTimer()
    minuterie.setSingleShot(True)
    expire = []
    minuterie.timeout.connect(lambda: (expire.append(1), job.cancel(), boucle.quit()))
    t0 = time.perf_counter()
    job.start()
    minuterie.start(DELAI_RENDU_S * 1000)
    if job.isActive():
        boucle.exec()
    minuterie.stop()
    duree = time.perf_counter() - t0
    erreurs = [_masque(e.message) for e in job.errors()]
    if expire:
        erreurs.append(f"rendu interrompu après {DELAI_RENDU_S} s")
    img = job.renderedImage()
    img.save(str(png))
    return img, erreurs, duree


def _mesurer(img):
    """``(part de pixels non transparents, nombre de couleurs distinctes)`` sur un pixel sur deux."""
    pleins, couleurs, total = 0, set(), 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            p = img.pixel(x, y)
            total += 1
            if (p >> 24) & 0xFF:
                pleins += 1
                couleurs.add(p)
    return (pleins / total if total else 0.0), len(couleurs)


def _juger(img, erreurs, image: bool):
    part, n = _mesurer(img)
    preuve = f"{part:.1%} de pixels peints, {n} couleurs"
    if erreurs:
        return False, preuve + " ; erreurs de rendu : " + " | ".join(erreurs[:3])
    # Une image doit remplir sa fenêtre ; un vecteur autour d'un objet trouvé peut n'être qu'un point.
    if part < (0.002 if image else 1e-9):
        return False, preuve + " : image vide"
    if image and n <= 2:
        return False, preuve + " : image uniforme"
    return True, preuve


# ---------------------------------------------------------------- emprises
def _vers_3857(lon, lat):
    r = 6378137.0
    return math.radians(lon) * r, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * r


def _case_couverte(couv, emprise):
    """Une case couverte de ``couverture.json`` (intérieure si possible), la plus proche du centre de
    l'emprise du fond, sinon du centre de sa couverture. ``None`` si rien n'est couvert."""
    from archeo.src.app.services import fonds_publics as fp

    cases = set(couv.cases) if couv else set()
    if not cases:
        return None
    interieures = [c for c in cases if all((c[0] + dx, c[1] + dy) in cases for dx in (-1, 0, 1) for dy in (-1, 0, 1))]
    choix = interieures or list(cases)
    if emprise:
        cible = ((emprise[0] + emprise[2]) / 2, (emprise[1] + emprise[3]) / 2)
    else:
        cs = [fp.centre_case(couv.zoom, x, y) for x, y in cases]
        cible = (sum(c[0] for c in cs) / len(cs), sum(c[1] for c in cs) / len(cs))

    def dist(c):
        lon, lat = fp.centre_case(couv.zoom, *c)
        return (lon - cible[0]) ** 2 + (lat - cible[1]) ** 2
    return min(choix, key=dist)


def _fenetre_image(fond, couv):
    """Rectangle EPSG:3857 où rendre une image : une case couverte, réduite si l'emprise du fond est plus
    petite (la case d'un fond local de 2 km n'en montrerait qu'un point)."""
    from qgis.core import QgsRectangle

    from archeo.src.app.services import fonds_publics as fp

    case = _case_couverte(couv, fond.emprise)
    if case is not None:
        o, s, e, n = fp.bornes_case(couv.zoom, *case)
    else:
        o, s, e, n = fond.emprise or (6.9, 48.8, 7.2, 49.0)
    if fond.emprise:  # recentrer dans l'emprise et ne pas la dépasser
        eo, es, ee, en = fond.emprise
        lon, lat = min(max((o + e) / 2, eo), ee), min(max((s + n) / 2, es), en)
        demi = min(e - o, (ee - eo) * 0.6) / 2
        o, s, e, n = lon - demi, lat - demi * 0.66, lon + demi, lat + demi * 0.66
    (x0, y0), (x1, y1) = _vers_3857(o, s), _vers_3857(e, n)
    c, d = ((x0 + x1) / 2, (y0 + y1) / 2), max(x1 - x0, y1 - y0) / 2
    return QgsRectangle(c[0] - d, c[1] - d, c[0] + d, c[1] + d)


def _premier_objet(couche, fond):
    """``(point EPSG:2154, où)`` du premier objet trouvé (filtre de dessin compris), ``(None, où)`` sinon."""
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsExpression, QgsExpressionContext,
                           QgsExpressionContextUtils, QgsFeatureRequest, QgsPointXY, QgsProject, QgsRectangle)

    l93 = QgsCoordinateReferenceSystem("EPSG:2154")
    vers = QgsCoordinateTransform(l93, couche.crs(), QgsProject.instance())
    retour = QgsCoordinateTransform(couche.crs(), l93, QgsProject.instance())
    essais = []
    if fond.emprise:
        wgs = QgsCoordinateReferenceSystem("EPSG:4326")
        e = QgsCoordinateTransform(wgs, l93, QgsProject.instance()).transformBoundingBox(QgsRectangle(*fond.emprise))
        c = e.center()
        essais += [(QgsRectangle(c.x() - 5000, c.y() - 5000, c.x() + 5000, c.y() + 5000), "10 km au centre de l'emprise"),
                   (e, "emprise entière")]
    else:
        x, y = FENETRAGE
        for d, ou in ((2500, "5 km autour de Fénétrange"), (25000, "50 km autour de Fénétrange")):
            essais.append((QgsRectangle(x - d, y - d, x + d, y + d), ou))
    # Le filtre de dessin s'évalue ici, côté poste : envoyé au service dans la demande, QGIS 4 ne reçoit
    # rien pour les ronds-points (constat 2026-11-18, cf. FondsPage._presente).
    filtre = QgsExpression(fond.filtre) if fond.filtre else None
    ctx = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(couche))
    for rect, ou in essais:
        for f in couche.getFeatures(QgsFeatureRequest().setFilterRect(vers.transformBoundingBox(rect))):
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            if filtre is not None:
                ctx.setFeature(f)
                if not filtre.evaluate(ctx):
                    continue
            # Un sommet, pas le centre : une surface dessinée en contour seul plus grande que la fenêtre
            # (zone de présomption) ne laisserait rien voir autour de son centre.
            p = g.vertexAt(0)
            return retour.transform(QgsPointXY(p.x(), p.y())), ou
    return None, " puis ".join(ou for _r, ou in essais)


# ---------------------------------------------------------------- contrôles
def _verdict(fam, ident, nom, service, ok, preuve, duree, messages):
    VERDICTS.setdefault(fam, {})[ident] = {
        "nom": nom, "service": service, "ok": ok, "preuve": _masque(preuve), "duree_s": round(duree, 2),
        "journal": [_masque(m)[:300] for m in dict.fromkeys(messages)][:6]}
    marque = "OK" if ok else ("--" if ok is None else "KO")
    log(f"  [{marque}] {ident} ({nom}) [{service}] {duree:.1f} s : {preuve}"
        + (f" | journal : {_masque(messages[0])[:200]}" if messages and ok is not True else ""))


def _fond(page, fond, fam, couv, msgs, vign: Path, familles=None):
    """Un fond par ``FondsPage.ajouter_fonds`` ; ``(ok, preuve, durée, service)``."""
    from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsRasterLayer, QgsRectangle

    from archeo.src.app.services import fonds_publics as fp

    service = ("WFS " + (fond.service_objets or fp.SERVICE_OBJETS)) if fond.objets else \
        ("WMS " + fond.wms if fond.wms else "WMTS " + page._service)
    t0 = time.perf_counter()
    ajoutes, _deja = page.ajouter_fonds([fond], visibles={fond.id},
                                        familles={fond.id: familles} if familles else None)
    couche = next((c for c in QgsProject.instance().mapLayers().values()
                   if c.customProperty(fp.PROPRIETE) == fond.id), None)
    t_couche = time.perf_counter() - t0
    if couche is None:
        # ajouter_fonds écarte une couche invalide sans un mot : la reconstruire pour lire pourquoi.
        brute = page._couche_objets(fond) if fond.objets else QgsRasterLayer(fp.uri_couche(page._service, fond), "x", "wms")
        err = brute.error().summary() or (brute.dataProvider().error().summary() if brute.dataProvider() else "")
        return False, f"couche non ajoutée par ajouter_fonds (invalide) : {err or 'aucune erreur fournie'}", t_couche, service
    png = vign / f"{fam}__{fond.id}.png"
    if fond.objets:
        if not couche.isSpatial():
            # Valide mais sans géométrie déclarée : QGIS ne la dessine jamais (Géorisques, 2026-11-18).
            return False, (f"couche valide mais sans géométrie (type {couche.wkbType()}, SCR "
                           f"« {couche.crs().authid()} ») : jamais dessinée"), time.perf_counter() - t0, service
        point, ou = _premier_objet(couche, fond)
        if point is None:
            err = couche.dataProvider().error().summary()
            if err:
                return False, f"aucun objet lu ({ou}) ; erreur du fournisseur : {err}", time.perf_counter() - t0, service
            return None, f"couche valide, aucun objet trouvé ({ou})", time.perf_counter() - t0, service
        d = FENETRE_OBJETS_M / 2
        rect = QgsRectangle(point.x() - d, point.y() - d, point.x() + d, point.y() + d)
        img, erreurs, t_rendu = _rendre(couche, rect, QgsCoordinateReferenceSystem("EPSG:2154"), png)
        ok, preuve = _juger(img, erreurs, image=False)
        preuve = f"objet trouvé ({ou}) à {point.x():.0f}, {point.y():.0f} ; " + preuve
    else:
        rect = _fenetre_image(fond, couv)
        img, erreurs, t_rendu = _rendre(couche, rect, QgsCoordinateReferenceSystem("EPSG:3857"), png)
        ok, preuve = _juger(img, erreurs, image=True)
        c = rect.center()
        preuve = f"fenêtre {rect.width() / 1000:.1f} km EPSG:3857 au centre {c.x():.0f}, {c.y():.0f} ; " + preuve
    prov = couche.dataProvider().error().summary() if couche.dataProvider() else ""
    if prov:
        preuve += f" ; erreur du fournisseur : {prov}"
    return ok, preuve + f" (couche {t_couche:.1f} s, rendu {t_rendu:.1f} s)", time.perf_counter() - t0, service


def _indice(dept_noms, item, msgs, vign: Path, ident: str):
    """Un indice du catalogue, construit comme ``VisualisationTab._open_indice``."""
    from qgis.core import QgsCoordinateReferenceSystem, QgsRasterLayer, QgsRectangle

    from archeo.src.ui.visualisation_tab import VisualisationTab

    service = "GDAL_WMS (flux)" if item.streamed else "fichier local (VRT)"
    t0 = time.perf_counter()
    erreur = VisualisationTab._sonder_flux(None, item) if item.streamed else None
    if erreur:
        return False, f"_sonder_flux : {erreur}", time.perf_counter() - t0, service
    couche = QgsRasterLayer(item.source, f"{item.info.sigle} — {dept_noms}", "gdal")
    if not couche.isValid():
        return False, f"couche invalide : {couche.error().summary()}", time.perf_counter() - t0, service
    if item.streamed:
        VisualisationTab._sans_etirement(None, couche)
        if item.extent:
            couche.setExtent(QgsRectangle(*[float(v) for v in item.extent]))
    t_couche = time.perf_counter() - t0
    l93 = QgsCoordinateReferenceSystem("EPSG:2154")
    tout = QgsRectangle(*[float(v) for v in item.extent]) if item.extent else couche.extent()
    c, d = tout.center(), FENETRE_DETAIL_M / 2
    preuves, oks, t_rendus = [], [], 0.0
    for suffixe, rect in (("emprise", tout), ("detail", QgsRectangle(c.x() - d, c.y() - d, c.x() + d, c.y() + d))):
        img, erreurs, t = _rendre(couche, rect, l93, vign / f"indices__{ident}__{suffixe}.png")
        t_rendus += t
        ok, preuve = _juger(img, erreurs, image=True)
        oks.append(ok)
        preuves.append(f"{suffixe} ({rect.width() / 1000:.1f} km) : {preuve} en {t:.1f} s")
    return all(oks), " ; ".join(preuves) + f" (couche {t_couche:.1f} s)", time.perf_counter() - t0, service


def _controler(fam, ident, nom, fn, msgs):
    from qgis.core import QgsProject
    resultat = None
    for essai in (1, 2):
        msgs.vider()
        try:
            ok, preuve, duree, service = fn()
        except Exception as e:  # noqa: BLE001 — une source cassée ne masque pas les autres
            ok, preuve, duree, service = False, f"{type(e).__name__} : {e} | {traceback.format_exc().splitlines()[-3]}", 0.0, "?"
        for _ in range(3):
            QgsProject.instance().clear()
        recus = msgs.vider()
        if essai == 2:
            preuve = f"2e essai : {preuve} || 1er essai : {resultat[1]}"
        resultat = (ok, preuve, duree, service, recus)
        if ok is not False:
            break
    ok, preuve, duree, service, recus = resultat
    _verdict(fam, ident, nom, service, ok, preuve, duree, recus)


def main() -> int:
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", type=Path, required=True)
    ap.add_argument("--seulement", default="")
    a = ap.parse_args()
    vign = a.sortie / "vignettes"
    vign.mkdir(parents=True, exist_ok=True)
    LOG = open(a.sortie / "controles.txt", "w", encoding="utf-8")
    app = _app(1)
    from qgis.core import Qgis, QgsNetworkAccessManager

    from archeo.src.app.services import fonds_publics as fp
    from archeo.src.app.services.visu_catalogue import load_catalogue, merge_catalogues
    from archeo.src.ui.fonds_page import FondsPage
    from archeo.src.ui.visualisation_tab import DEFAULT_CATALOGUE, LOCAL_CATALOGUE

    QgsNetworkAccessManager.setTimeout(30000)
    log(f"QGIS {Qgis.version()}")
    msgs = _Messages()
    garder = (lambda i: a.seulement in i) if a.seulement else (lambda i: True)

    # 1. Catalogue des indices : une source distincte par (clé, source, emprise), départements regroupés.
    cat = load_catalogue(RACINE / DEFAULT_CATALOGUE)
    local = RACINE / LOCAL_CATALOGUE
    if local.is_file():
        cat = merge_catalogues(cat, load_catalogue(local), local.parent)
    uniques: dict = {}
    for d in cat.covered:
        for it in d.items:
            uniques.setdefault((it.key, it.source, tuple(it.extent or ())), (it, []))[1].append(d.name)
    log(f"\n== Catalogue des indices : {cat.product_count} entrées, {len(uniques)} sources distinctes ==")
    for n, (it, noms) in enumerate(uniques.values()):
        ident = f"{it.key}_{re.sub(r'[^A-Za-z0-9]+', '_', Path(it.source).parent.parent.name or Path(it.source).stem)}_{n:02d}"
        if not garder(ident):
            continue
        dn = noms[0] + (f" (+{len(noms) - 1} départements)" if len(noms) > 1 else "")
        _controler("indices", ident, f"{it.info.sigle} — {dn}", lambda it=it, dn=dn, ident=ident: _indice(dn, it, msgs, vign, ident), msgs)

    # 2. Fonds publics, sources à l'essai, contexte moderne : par la page du plugin.
    page = FondsPage(RACINE)
    couvs = fp.charger_couvertures(RACINE / fp.COUVERTURE)
    familles = (("fonds", page._fonds), ("essais", page._essais))
    for fam, fonds in familles:
        log(f"\n== {fam} : {len(fonds)} sources ==")
        for fond in fonds:
            if garder(fond.id):
                _controler(fam, fond.id, fond.nom_couche,
                           lambda f=fond, fam=fam: _fond(page, f, fam, couvs.get(f.id), msgs, vign), msgs)
    connus = {f.id for f in page._fonds}
    ctx = fp.couches_contexte(page._fonds)
    log(f"\n== contexte moderne : {len(ctx)} couches ==")
    for famille, fond, _cochee in ctx:
        if not garder(fond.id):
            continue
        if fond.id in connus:
            _verdict("contexte", fond.id, fond.titre, "WFS", None, f"même couche que « {fond.id} » du catalogue, "
                     "contrôlée dans « fonds »", 0.0, [])
            continue
        _controler("contexte", fond.id, f"{famille} · {fond.titre}",
                   lambda f=fond, g=famille: _fond(page, f, "contexte", None, msgs, vign, familles=g), msgs)

    (a.sortie / "verdicts.json").write_text(_masque(json.dumps(VERDICTS, ensure_ascii=False, indent=1)),
                                            encoding="utf-8")
    log("\n== Bilan ==")
    ko = 0
    for fam, v in VERDICTS.items():
        n_ok = sum(1 for x in v.values() if x["ok"] is True)
        n_ko = sum(1 for x in v.values() if x["ok"] is False)
        ko += n_ko
        lents = [i for i, x in v.items() if x["duree_s"] > 5]
        log(f"{fam} : {len(v)} testées, {n_ok} OK, {n_ko} KO, {len(v) - n_ok - n_ko} sans objet"
            + (f" ; lentes (> 5 s) : {', '.join(lents)}" if lents else ""))
    log("RESULTAT : OK" if not ko else "RESULTAT : ECHEC")
    LOG.close()
    app.exitQgis()
    return 0 if not ko else 1


if __name__ == "__main__":
    sys.exit(main())
