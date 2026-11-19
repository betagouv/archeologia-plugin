"""Croisement géométrique des détections avec la BD TOPO (bâtiments, surfaces en eau).

Les règles et les phrases sont dans :mod:`contexte_moderne` ; ce module fait le reste :

0. cinq données : bâtiments, surfaces en eau, et — pour les structures ponctuelles — cours d'eau, zones
   d'habitation et ronds-points (les tronçons de route de nature « Rond-point », refermés en disques) ; les
   lieux-dits en sont sortis le 2026-11-18 ;
1. :func:`cellules` découpe l'emprise des détections en carrés de 10 km (une requête WFS par carré
   occupé, paginée par 5 000 : un run de 60 × 36 km ne tient pas en une seule requête) ;
2. :func:`telecharger` lit les objets d'une couche WFS de la Géoplateforme sur ces carrés, en Lambert-93 ;
3. :func:`croiser` calcule, pour chaque détection, la distance et la part recouverte de chaque objet
   proche (index spatial ``STRtree``), puis les cinq champs par :func:`contexte_moderne.champs`.

Pas de Qt ni de QGIS : ``shapely`` seulement, importé à l'usage (comme ``pipeline.cv``). Le réseau est
injecté (``lire_json``) : le plugin passe sa propre fonction, qui suit le proxy du poste ; les tests
passent des objets en mémoire.
"""
from __future__ import annotations

import json
import math
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import contexte_moderne as cm

SERVICE_WFS = "https://data.geopf.fr/wfs/ows"
#: Couche WFS par source, et attributs gardés (les autres ne servent ni aux règles ni aux phrases).
COUCHES = {
    cm.BATIMENT: ("BDTOPO_V3:batiment",
                  ("nature", "usage_1", "etat_de_l_objet", "construction_legere")),
    cm.EAU: ("BDTOPO_V3:surface_hydrographique",
             ("nature", "origine", "persistance", "cpx_toponyme_de_plan_d_eau")),
    cm.COURS_EAU: ("BDTOPO_V3:troncon_hydrographique",
                   ("nature", "origine", "persistance", "cpx_toponyme_de_cours_d_eau")),
    cm.HABITATION: ("BDTOPO_V3:zone_d_habitation", ("nature", "toponyme")),
    cm.ROND_POINT: ("BDTOPO_V3:troncon_de_route", ("nature",)),
}
#: Filtre côté serveur : on ne télécharge pas toutes les routes pour n'en garder que les ronds-points.
FILTRES = {cm.ROND_POINT: "nature='Rond-point'"}
#: La donnée du Catalogue des flux qui correspond à chaque source : son titre est écrit dans
#: ``contexte_source``, pour que l'utilisateur la retrouve et l'ajoute au projet.
ID_CATALOGUE = {cm.BATIMENT: "batiments", cm.EAU: "surfaces_en_eau", cm.COURS_EAU: "cours_eau",
                cm.HABITATION: "zones_habitation", cm.ROND_POINT: "ctx_ronds_points"}
CELLULE_M = 10_000.0
PAGE = 5000

Bbox = Tuple[float, float, float, float]


def cellules(emprises: Iterable[Bbox], marge: float = cm.RAYON_RECHERCHE, cote: float = CELLULE_M) -> List[Bbox]:
    """Les carrés de ``cote`` m (calés sur la grille de ``cote`` m) que touchent les emprises des
    détections élargies de ``marge``, dans un ordre stable. Aucune détection → aucune requête."""
    occupees = set()
    for x0, y0, x1, y1 in emprises:
        for i in range(math.floor((x0 - marge) / cote), math.floor((x1 + marge) / cote) + 1):
            for j in range(math.floor((y0 - marge) / cote), math.floor((y1 + marge) / cote) + 1):
                occupees.add((i, j))
    return [(i * cote, j * cote, (i + 1) * cote, (j + 1) * cote) for i, j in sorted(occupees)]


def url_page(typename: str, bbox: Bbox, debut: int, service: str = SERVICE_WFS, page: int = PAGE,
             filtre: str = "") -> str:
    """GetFeature GeoJSON en Lambert-93 d'une page d'objets d'un carré. ⚠ La Géoplateforme refuse les
    paramètres ``BBOX`` et ``CQL_FILTER`` ensemble : avec un ``filtre``, l'emprise passe dans le filtre."""
    x0, y0, x1, y1 = bbox
    tete = (f"{service}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES={typename}"
            f"&OUTPUTFORMAT=application/json&SRSNAME=EPSG:2154&COUNT={page}&STARTINDEX={debut}&SORTBY=cleabs")
    if filtre:
        from urllib.parse import quote

        return tete + "&CQL_FILTER=" + quote(f"{filtre} AND BBOX(geometrie,{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f},'EPSG:2154')")
    return tete + f"&BBOX={x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f},EPSG:2154"


#: Essais par page avant d'abandonner (2026-11-18 : un 504 isolé annulait tout le croisement).
ESSAIS_PAGE = 3


def telecharger(source: str, carres: Sequence[Bbox], lire_json: Callable[[str], Mapping[str, Any]],
                annule: Callable[[], bool] = lambda: False,
                pause: Callable[[float], None] = time.sleep) -> List[Dict[str, Any]]:
    """Les objets GeoJSON (``geometry`` + ``properties`` réduites) d'une source sur ces carrés.

    Un objet à cheval sur deux carrés revient deux fois : on garde la première occurrence (``cleabs``).
    Une page en erreur est redemandée (``ESSAIS_PAGE`` fois, 1 s puis 2 s d'attente) ; au-delà, l'erreur
    remonte : c'est à l'appelant de décider (le traitement n'échoue jamais pour ça).
    """
    def page_lue(url: str) -> Mapping[str, Any]:
        for essai in range(ESSAIS_PAGE):
            try:
                return lire_json(url)
            except Exception:                      # noqa: BLE001 — réseau, réponse non JSON, 5xx
                if essai == ESSAIS_PAGE - 1 or annule():
                    raise
                pause(float(essai + 1))
        raise AssertionError("inatteignable")

    typename, gardes = COUCHES[source]
    vus, objets = set(), []
    for carre in carres:
        debut = 0
        while True:
            if annule():
                return objets
            page = page_lue(url_page(typename, carre, debut, filtre=FILTRES.get(source, "")))
            entites = page.get("features") or []
            for f in entites:
                props = f.get("properties") or {}
                cle = props.get("cleabs") or f.get("id")
                if cle in vus or not f.get("geometry"):
                    continue
                vus.add(cle)
                objets.append({"geometry": f["geometry"], "properties": {k: props.get(k) for k in gardes}})
            if len(entites) < PAGE:
                break
            debut += PAGE
    return objets


def croiser(detections: Sequence[Any], objets_par_source: Mapping[str, Sequence[Mapping[str, Any]]],
            structure: str, source: str, titres: Optional[Mapping[str, str]] = None,
            date_iso: str = "") -> List[Dict[str, Any]]:
    """Les cinq champs de chaque détection (géométries shapely en Lambert-93), dans leur ordre.

    ``objets_par_source`` : ``{cm.BATIMENT: [objet GeoJSON…], cm.EAU: […]}``. Une géométrie de
    détection vide ou invalide reçoit des champs vides, sauf la source.
    """
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    geoms, meta, anneaux = [], [], []
    for nom, objets in objets_par_source.items():
        if nom in cm.SOURCES_PONCTUELLES and cm.est_lineaire(structure):
            continue
        for o in objets:
            try:
                g = shape(o["geometry"])
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if g.is_empty:
                continue
            if nom == cm.ROND_POINT:
                anneaux.append(g)                       # des tronçons : refermés en disques plus bas
                continue
            if not g.is_valid:
                g = g.buffer(0)
            geoms.append(g)
            meta.append((nom, o.get("properties") or {}))
    if anneaux:
        from shapely.ops import polygonize, unary_union

        for disque in polygonize(unary_union(anneaux)):
            geoms.append(disque)
            meta.append((cm.ROND_POINT, {"nature": "Rond-point"}))
    arbre = STRtree(geoms) if geoms else None
    sortie = []
    for det in detections:
        proches: List[cm.Objet] = []
        if arbre is not None and det is not None and not det.is_empty:
            d = det if det.is_valid else det.buffer(0)
            aire = d.area or 0.0
            for k in arbre.query(d.buffer(cm.RAYON_RECHERCHE)):
                g = geoms[int(k)]
                distance = d.distance(g)
                if distance > cm.RAYON_RECHERCHE:
                    continue
                part = (d.intersection(g).area / aire) if (aire and distance == 0) else 0.0
                proches.append(cm.Objet(meta[int(k)][0], meta[int(k)][1], distance, part))
        sortie.append(cm.champs(proches, structure, source, titres, date_iso))
    return sortie


def lire_json_urllib(url: str, proxy: Optional[str] = None, delai: float = 90.0) -> Mapping[str, Any]:
    """Lecteur par défaut (outils de développement, tests de bout en bout) ; le plugin passe le sien."""
    import urllib.request

    poignees = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
    ouvreur = urllib.request.build_opener(*poignees)
    with ouvreur.open(urllib.request.Request(url, headers={"User-Agent": "QGIS"}), timeout=delai) as rep:
        return json.loads(rep.read().decode("utf-8"))
