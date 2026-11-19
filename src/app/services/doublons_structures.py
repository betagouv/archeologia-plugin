"""Un même objet détecté sous deux structures (2026-11-12) : les deux détections sont gardées, et
chacune nomme l'autre dans son champ ``aussi_vu_comme`` (« Charbonnières (probable, 68 %) »).

Rien n'est supprimé ni départagé : sur le test qui a motivé la règle, la charbonnière réelle était à
68 % et la dépression à 71 % — choisir « la plus fiable » aurait gardé la mauvaise. Appelé par
``finalize_pipeline`` (fil de travail : ni QGIS ni Qt), sans réseau.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

from . import contexte_gpkg as cg

CHAMP = "aussi_vu_comme"
#: Deux détections sont « le même objet » quand leur intersection vaut au moins cette part de leur
#: union. Mesuré sur D:/pipeline_results/test : les 80 paires dépression/charbonnière sont ≥ 0,3 ;
#: un linéaire qui traverse un objet ponctuel reste presque toujours < 0,3 (1 cas sur 45).
IOU_MIN = 0.3


def libelle(couche: str, fiabilite: Optional[str], pct: Optional[float]) -> str:
    if not fiabilite:
        return couche
    return f"{couche} ({fiabilite.lower()}, {pct:.0f} %)" if pct is not None else f"{couche} ({fiabilite.lower()})"


def _attributs(gpkg: Path, couche: str) -> dict:
    """``fid → (classe, fiabilité, pour cent)`` ; un champ absent vaut ``None``."""
    with closing(sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)) as con:     # fermé : pas de verrou Windows
        infos = list(con.execute(f'PRAGMA table_info("{couche}")'))
        cle = next((r[1] for r in infos if r[5]), "fid")
        presents = {r[1] for r in infos}
        cols = ", ".join(f'"{c}"' if c in presents else "NULL" for c in ("model_pred", "fiabilite", "fiabilite_pct"))
        return {r[0]: r[1:] for r in con.execute(f'SELECT "{cle}", {cols} FROM "{couche}"')}


def marquer(det_dir: Path) -> int:
    """Écrit ``aussi_vu_comme`` dans toutes les couches de détections (vide quand l'objet est seul, ce
    qui efface une marque d'un traitement précédent). Renvoie le nombre d'objets marqués."""
    from shapely.strtree import STRtree

    couches = []
    for gpkg, couche in cg.couches_de_detections(Path(det_dir)):
        fids, geoms = cg.lire_geometries(gpkg, couche)
        attrs = _attributs(gpkg, couche)
        couches.append((gpkg, couche, fids, geoms, [attrs.get(f, (None, None, None)) for f in fids],
                        [[] for _ in fids]))
    for a, (_ga, nom_a, _fa, geoms_a, attrs_a, vus_a) in enumerate(couches):
        for _gb, nom_b, _fb, geoms_b, attrs_b, vus_b in couches[a + 1:]:
            if not geoms_a or not geoms_b:
                continue
            arbre = STRtree(geoms_b)
            for i, g in enumerate(geoms_a):
                if g is None or g.is_empty:
                    continue
                for k in arbre.query(g):
                    h = geoms_b[k]
                    if attrs_a[i][0] and attrs_a[i][0] == attrs_b[k][0]:
                        continue            # même classe (comparaison A/B, sources d'un regroupement)
                    inter = g.intersection(h).area
                    if inter and inter / (g.area + h.area - inter) >= IOU_MIN:
                        vus_a[i].append(libelle(nom_b, *attrs_b[k][1:]))
                        vus_b[k].append(libelle(nom_a, *attrs_a[i][1:]))
    marques = 0
    for gpkg, couche, fids, _geoms, _attrs, vus in couches:
        cg.ecrire_champs(gpkg, couche, fids, [{CHAMP: " ; ".join(dict.fromkeys(v)) or None} for v in vus],
                         types={CHAMP: "TEXT"})
        marques += sum(1 for v in vus if v)
    return marques
