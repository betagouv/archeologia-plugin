# -*- coding: utf-8 -*-
"""Contrôle de l'affichage d'un vrai dossier de sortie, hors écran (2026-11-18).

Ouvre ``livrable/projet.qgs`` sans QGIS de bureau et vérifie que chaque couche montre ce que ses
données contiennent — ce que les tests unitaires ne voient pas sur un vrai traitement :

* projet relu, couches valides, chemins relatifs (le livrable se transmet) ;
* arborescence : groupe « Structures » pour les détections, CRS = celui de ``traitement.json`` ;
* détections : chaque objet tombe dans une catégorie de la légende (rendu catégorisé = égalité
  exacte, sans « autres valeurs » : un objet hors légende ne s'affiche pas), effectifs = bilan de
  ``traitement.json``, cases cochées = ``fiabilite.visible_par_defaut``, contour seul, une couleur
  par structure, une couche par entité ayant des objets ;
* indices : mosaïque valide, NoData posé, toutes ses dalles présentes ;
* ``traitement.json`` sans chemin de poste.

Les attentes viennent du code du plugin (pas de copie des règles). Écrit ``<sortie>/verdicts.json``
(un verdict par dossier et par point : ``ok`` vrai/faux/null = sans objet, ``preuve``) et
``<sortie>/controles.txt``, terminé par ``RESULTAT : OK`` ou ``RESULTAT : ECHEC``.

    C:/OSGeo4W/bin/python-qgis.bat dev/controle_livrable.py D:/pipeline_results/test --sortie D:/brouillons/controle_q3
    "C:/Program Files/QGIS 4.0.3/bin/python-qgis.bat" dev/controle_livrable.py --connus --sortie D:/brouillons/controle_q4

``--connus`` : tous les dossiers de ``runs_connus.json`` du profil QGIS 3 qui ont un ``projet.qgs``.
À lancer sous les deux QGIS.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rendu_hors_ecran import _app  # noqa: E402

VERDICTS: dict = {}
LOG = None
_CHEMIN_POSTE = re.compile(r"(?i)\b[a-z]:[\\/]|/users/|/home/")


def log(*parts):
    ligne = " ".join(str(p) for p in parts)
    LOG.write(ligne + "\n")
    LOG.flush()


def verdict(dossier: str, point: str, ok, preuve: str) -> None:
    VERDICTS.setdefault(dossier, {})[point] = {"ok": ok, "preuve": preuve}
    log(f"  [{'OK' if ok else ('--' if ok is None else 'KO')}] {point} : {preuve}")


def _evaluer_categories(layer):
    """``Counter`` valeur de classement → nombre d'objets (expression évaluée comme le rendu)."""
    from qgis.core import QgsExpression, QgsExpressionContext, QgsExpressionContextUtils

    expr = QgsExpression(layer.renderer().classAttribute())
    ctx = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
    expr.prepare(ctx)
    compte = collections.Counter()
    for f in layer.getFeatures():
        ctx.setFeature(f)
        compte[str(expr.evaluate(ctx))] += 1
    return compte


def _sources_vrt(vrt: Path):
    racine = ET.parse(vrt).getroot()
    for el in racine.iter("SourceFilename"):
        p = Path(el.text or "")
        yield p if el.get("relativeToVRT") != "1" else vrt.parent / p


def controler(dossier: Path) -> None:
    from qgis.core import QgsCategorizedSymbolRenderer, QgsProject, QgsRasterLayer, QgsVectorLayer

    from archeo.src.app.services import contexte_moderne as cm
    from archeo.src.app.services import fiabilite as fb

    d = str(dossier)
    log(f"\n== {d}")
    qgs = dossier / "livrable" / "projet.qgs"
    trace_p = dossier / "livrable" / "traitement.json"
    if not qgs.is_file() or not trace_p.is_file():
        verdict(d, "livrable", False, "projet.qgs ou traitement.json absent")
        return
    trace = json.loads(trace_p.read_text(encoding="utf-8"))
    log(f"  plugin {trace.get('plugin_version')} · {trace.get('date')} · CRS {trace.get('crs')}")

    texte_trace = trace_p.read_text(encoding="utf-8")
    poste = sorted(set(_CHEMIN_POSTE.findall(texte_trace)))
    verdict(d, "trace_sans_chemin_poste", not poste, f"motifs trouvés : {poste}" if poste else "aucun chemin absolu")

    xml_qgs = qgs.read_text(encoding="utf-8", errors="replace")
    absolus = sorted({m for m in re.findall(r"<datasource>([^<]*)</datasource>", xml_qgs) if _CHEMIN_POSTE.match(m)})
    verdict(d, "projet_chemins_relatifs", not absolus,
            f"{len(absolus)} source(s) en chemin absolu, ex. {absolus[0][:90]}" if absolus else "toutes relatives")

    projet = QgsProject.instance()
    projet.clear()
    if not projet.read(str(qgs)):
        verdict(d, "projet_relu", False, projet.error())
        return
    couches = list(projet.mapLayers().values())
    invalides = [c.name() for c in couches if not c.isValid()]
    verdict(d, "couches_valides", not invalides, f"{len(couches)} couches" + (f", invalides : {invalides}" if invalides else ""))

    crs = str(trace.get("crs") or "EPSG:2154")
    autres = [f"{c.name()}={c.crs().authid()}" for c in couches if c.isValid() and c.crs().authid() != crs]
    verdict(d, "crs", projet.crs().authid() == crs and not autres,
            f"projet {projet.crs().authid()}, attendu {crs}" + (f" ; couches : {autres}" if autres else ""))

    # --- Arborescence : détections sous « Structures » (recherche récursive du groupe).
    groupe = projet.layerTreeRoot().findGroup("Structures")
    sous_structures = set(groupe.findLayerIds()) if groupe else set()
    detections = [c for c in couches if isinstance(c, QgsVectorLayer) and c.isValid()
                  and "/livrable/detections/" in c.source().replace("\\", "/")]
    hors = [c.name() for c in detections if c.id() not in sous_structures]
    verdict(d, "groupe_structures", not hors if detections else None,
            "aucune couche de détection" if not detections else
            (f"hors du groupe : {hors}" if hors else f"{len(detections)} couches sous « Structures »"))

    # --- Une couche par entité qui a des objets.
    bilan = {b.get("couche"): b for b in (trace.get("bilan_fiabilite") or [])}
    noms = {c.name() for c in detections}
    manquantes = [b["couche"] for b in bilan.values() if int(b.get("total") or 0) > 0 and b["couche"] not in noms]
    verdict(d, "couche_par_entite", not manquantes if bilan else None,
            "pas de bilan dans la trace" if not bilan else
            (f"entités avec objets sans couche : {manquantes}" if manquantes else f"{len(bilan)} entités, toutes présentes"))

    # --- Détections, couche par couche.
    couleurs = {}
    for c in detections:
        nom = c.name()
        r = c.renderer()
        if not isinstance(r, QgsCategorizedSymbolRenderer):
            verdict(d, f"{nom} · rendu", None, f"rendu {r.type()} (zone de synthèse ou symbole unique)")
            continue
        compte = _evaluer_categories(c)
        cats = {str(k.value()): k for k in r.categories()}
        orphelins = {v: n for v, n in compte.items() if v not in cats}
        verdict(d, f"{nom} · légende couvre les objets", not orphelins,
                f"{sum(orphelins.values())} objet(s) invisibles, valeurs {list(orphelins)[:5]}" if orphelins
                else f"{sum(compte.values())} objets, tous dans une catégorie")

        pleins = [v for v, k in cats.items()
                  if any(getattr(sl, "fillColor", None) and sl.fillColor().alpha() > 0 for sl in k.symbol().symbolLayers())]
        verdict(d, f"{nom} · contour seul", not pleins, f"remplissage visible : {pleins}" if pleins else "aucun remplissage")

        entree, classe = None, ""
        try:
            gpkg, _, table = c.source().partition("|layername=")
            entree = fb.read_sidecar(gpkg, table or Path(gpkg).stem)
            classe = str((entree or {}).get("classe") or "")
        except Exception:  # noqa: BLE001
            pass
        par_label = {lab: cle for cle, lab in fb.LABELS_FR.items()}
        mauvais = []
        for v, k in cats.items():
            attendu = False if v == cm.CATEGORIE_LEGENDE else (
                fb.visible_par_defaut(par_label[v], classe) if v in par_label else True)
            if k.renderState() != attendu:
                mauvais.append(f"{v} coché={k.renderState()} attendu={attendu}")
        verdict(d, f"{nom} · cases cochées", not mauvais, "; ".join(mauvais) if mauvais else f"conformes (classe « {classe or '?'} »)")

        b = bilan.get(nom)
        if b and "fiabilite" in r.classAttribute():
            attendu = {fb.LABELS_FR.get(k, k): int(n) for k, n in (b.get("effectifs") or {}).items() if int(n)}
            if int(b.get("ecartees") or 0):
                attendu[cm.CATEGORIE_LEGENDE] = int(b["ecartees"])
            vu = {k: n for k, n in compte.items() if n}
            verdict(d, f"{nom} · effectifs = bilan", vu == attendu, f"carte {dict(sorted(vu.items()))} / bilan {dict(sorted(attendu.items()))}")
        elif b is None and bilan:
            verdict(d, f"{nom} · effectifs = bilan", False, "couche absente du bilan de traitement.json")

        if "fiabilite" in r.classAttribute():
            resume = (c.metadata().abstract() or "").splitlines()[:1]
            tip = c.mapTipTemplate() or ""
            ok = bool(resume) and f"« {nom} »" in resume[0] and '"model_pred"' not in tip and f"<b>{nom}</b>" in tip
            verdict(d, f"{nom} · infobulle et résumé nomment la structure", ok,
                    f"résumé « {resume[0][:70] if resume else '<vide>'} », infobulle "
                    + ("par libellé" if f"<b>{nom}</b>" in tip else "par identifiant de classe"))

        base = cats.get(fb.LABELS_FR["possible"]) or next(iter(cats.values()))
        couleurs.setdefault(base.symbol().symbolLayer(0).strokeColor().name(), []).append(nom)

    if detections:
        doublons = {k: v for k, v in couleurs.items() if len(v) > 1}
        verdict(d, "une couleur par structure", not doublons, f"couleur partagée : {doublons}" if doublons else f"{len(couleurs)} couleurs distinctes")

    # --- Indices.
    for c in couches:
        if not isinstance(c, QgsRasterLayer):
            continue
        src = Path(c.source())
        if src.suffix.lower() != ".vrt" or not src.is_file():
            verdict(d, f"{c.name()} · mosaïque", src.is_file(), f"source {src.name}")
            continue
        sources = list(_sources_vrt(src))
        absentes = [p.name for p in sources if not p.is_file()]
        nodata = c.dataProvider().sourceHasNoDataValue(1)
        ok = c.isValid() and not absentes and nodata
        verdict(d, f"{c.name()} · mosaïque", ok,
                f"{len(sources)} dalles" + (f", absentes : {absentes[:3]}" if absentes else "")
                + ("" if nodata else ", NoData non posé"))
    projet.clear()


def _connus():
    reg = Path(os.environ["APPDATA"]) / "QGIS" / "QGIS3" / "profiles" / "default" / "archeologia" / "runs_connus.json"
    vus = []
    for e in json.loads(reg.read_text(encoding="utf-8")):
        p = Path(e["output_dir"])
        if (p / "livrable" / "projet.qgs").is_file() and p not in vus:
            vus.append(p)
    return vus


def main() -> int:
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("dossiers", nargs="*", type=Path)
    ap.add_argument("--connus", action="store_true")
    ap.add_argument("--sortie", type=Path, required=True)
    a = ap.parse_args()
    a.sortie.mkdir(parents=True, exist_ok=True)
    LOG = open(a.sortie / "controles.txt", "w", encoding="utf-8")
    app = _app(1)
    from qgis.core import Qgis
    log(f"QGIS {Qgis.version()}")
    dossiers = list(a.dossiers) + (_connus() if a.connus else [])
    for dossier in dossiers:
        try:
            controler(dossier)
        except Exception as e:  # noqa: BLE001 — un dossier cassé ne masque pas les autres
            verdict(str(dossier), "exception", False, f"{type(e).__name__} : {e} | {traceback.format_exc().splitlines()[-3]}")
    (a.sortie / "verdicts.json").write_text(json.dumps(VERDICTS, ensure_ascii=False, indent=1), encoding="utf-8")
    ko = sum(1 for v in VERDICTS.values() for x in v.values() if x["ok"] is False)
    log(f"\n{len(dossiers)} dossier(s), {ko} KO")
    log("RESULTAT : OK" if not ko else "RESULTAT : ECHEC")
    LOG.close()
    app.exitQgis()
    return 0 if not ko else 1


if __name__ == "__main__":
    sys.exit(main())
