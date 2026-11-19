"""Applique le croisement « contexte moderne » à un traitement **déjà fait**, puis écrit un projet QGIS.

Le plugin fait ce croisement à la fin de chaque traitement (option de l'étape 4). Cet outil le rejoue
sur un dossier de sortie existant, sans relancer la détection : mêmes fonctions
(``app/services/contexte_gpkg.marquer``), même fabrique de couches que le plugin
(``ui/layer_loader.build_detection_vector_layer``, donc la même catégorie grise de la légende).

    C:/OSGeo4W/bin/python-qgis.bat dev/contexte_moderne.py <dossier de sortie> [--projet-seul]

- écrit les cinq champs ``contexte_*`` dans ``livrable/detections/**.gpkg`` (réseau : BD TOPO de l'IGN) ;
- écrit ``livrable/projet_contexte.qgs`` : les mosaïques d'indices, puis le groupe « Structures » ;
- écrit le bilan dans ``livrable/contexte_moderne.json`` et dans ``<sortie>/contexte_moderne.txt``.

``--projet-seul`` réécrit le projet sans refaire le croisement. Le ``.bat`` avale la sortie : lire le
fichier texte.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
RACINE = Path(__file__).resolve().parents[1]
_pkg = types.ModuleType("archeo")
_pkg.__path__ = [str(RACINE)]
sys.modules["archeo"] = _pkg


def _projet(livrable: Path, journal) -> Path:
    from qgis.core import QgsProject, QgsRasterLayer

    from archeo.src.app.services.contexte_gpkg import couches_de_detections
    from archeo.src.pipeline.cv.color_palette import base_color_for_rank
    from archeo.src.ui.layer_loader import build_detection_vector_layer

    class _Log:
        def warning(self, m):
            journal("  ⚠ " + str(m))

        info = debug = error = warning

    projet = QgsProject.instance()
    projet.clear()
    projet.setCrs(__import__("qgis.core", fromlist=["QgsCoordinateReferenceSystem"]).QgsCoordinateReferenceSystem("EPSG:2154"))
    racine = projet.layerTreeRoot()
    for vrt in sorted((livrable / "indices").glob("*/tif/index_*.vrt")):
        couche = QgsRasterLayer(str(vrt), vrt.parent.parent.name, "gdal")
        if couche.isValid():
            projet.addMapLayer(couche, False)
            racine.addLayer(couche)
    groupe = racine.insertGroup(0, "Structures")
    for rang, (gpkg, nom) in enumerate(couches_de_detections(livrable / "detections")):
        couche = build_detection_vector_layer(f"{gpkg}|layername={nom}", nom, base_color=base_color_for_rank(rang),
                                              confidence_threshold=0.3, logger=_Log())
        if couche is not None:
            projet.addMapLayer(couche, False)
            groupe.addLayer(couche)
    chemin = livrable / "projet_contexte.qgs"
    projet.write(str(chemin))
    return chemin


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sortie", type=Path, help="dossier de sortie d'un traitement (contient livrable/)")
    ap.add_argument("--projet-seul", action="store_true", help="réécrit le projet sans refaire le croisement")
    a = ap.parse_args(argv)
    livrable = a.sortie / "livrable"
    lignes = []

    def journal(m):
        lignes.append(str(m))
        (a.sortie / "contexte_moderne.txt").write_text("\n".join(lignes), encoding="utf-8")

    from qgis.core import QgsApplication

    app = QgsApplication([], False)
    app.initQgis()
    from archeo.src.app.services import contexte_croisement, contexte_gpkg

    if not a.projet_seul:
        try:
            crs = json.loads((livrable / "traitement.json").read_text(encoding="utf-8")).get("crs") or "EPSG:2154"
        except (OSError, ValueError):
            crs = "EPSG:2154"
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        bilan = contexte_gpkg.marquer(livrable / "detections",
                                      lambda u: contexte_croisement.lire_json_urllib(u, proxy=proxy),
                                      crs=crs, journal=journal)
        journal(bilan.phrase or "Aucune détection.")
        for slug, (t, m, i) in sorted(bilan.par_structure.items()):
            journal(f"  {slug} : {t} détections, {m} en contexte moderne, {i} informées")
        (livrable / "contexte_moderne.json").write_text(json.dumps(bilan.en_dict(), ensure_ascii=False, indent=1),
                                                        encoding="utf-8")
    chemin = _projet(livrable, journal)
    journal(f"projet écrit : {chemin}")
    journal("RESULTAT : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
