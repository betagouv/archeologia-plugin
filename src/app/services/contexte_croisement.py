"""Croisement géométrique des détections avec la BD TOPO (bâtiments, surfaces en eau).

Les règles et les phrases sont dans :mod:`contexte_moderne` ; ce module fait le reste :

0. cinq données : bâtiments, surfaces en eau, et — pour les structures ponctuelles — cours d'eau, zones
   d'habitation et ronds-points (les tronçons de route de nature « Rond-point », refermés en disques) ; les
   lieux-dits en sont sortis le 2026-11-18 ;
1. :func:`cellules` découpe l'emprise des détections en carrés de 10 km et, dans chaque carré occupé, ne
   garde que l'emprise des détections élargie de la marge (une requête WFS par carré, paginée par 5 000 :
   un run de 60 × 36 km ne tient pas en une seule requête) ;
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
    # linéaires (2026-11-19) : ce qu'un talus ou un chemin creux peut longer
    cm.ROUTE: ("BDTOPO_V3:troncon_de_route", ("nature",)),
    cm.VOIE_FERREE: ("BDTOPO_V3:troncon_de_voie_ferree", ("nature",)),
    cm.TALUS_IGN: ("BDTOPO_V3:ligne_orographique", ("nature",)),
    cm.CANALISATION: ("BDTOPO_V3:canalisation", ("nature",)),
    # patrimoine connu (2026-11-19) : Géoplateforme (servitudes, plans d'urbanisme) et services régionaux
    cm.MONUMENT: ("wfs_sup:generateur_sup_s", ("suptype", "nomsuplitt", "nomgen")),
    cm.PLU_ZONE: ("wfs_du:info_surf", ("typeinf", "libelle")),
    cm.PLU_POINT: ("wfs_du:info_pct", ("typeinf", "libelle")),
    cm.ZPPA_BRETAGNE: ("drac:bretagne_zppa", ("COMMUNE", "N_ZONE")),
    cm.ZPPA_AURA: ("ms:n_atlaspatrimoine_zppa_s_r84", ("comm_nom", "prot_objet")),
    cm.ZPPA_CVL: ("zppa_cvl_executoire_2025_gpkg_06-03-2026_wfs:zppa_cvl_executoire_2025", ("communes", "zone")),
}
#: Données dont une panne ne compromet pas le croisement (2026-11-19) : elles ne font qu'informer, ou viennent
#: d'un autre service ; leur absence est dite au journal et le reste est écrit. Les cinq premières données,
#: elles, décident des exclusions : sans elles, rien n'est écrit (comme avant).
FACULTATIVES = frozenset({cm.ROUTE, cm.VOIE_FERREE, cm.TALUS_IGN, cm.CANALISATION, *cm.SOURCES_PATRIMOINE})
#: Service WFS d'une donnée qui n'est pas sur la Géoplateforme.
SERVICES: Dict[str, str] = {cm.ZPPA_BRETAGNE: "https://geobretagne.fr/geoserver/drac/ows",
                             cm.ZPPA_AURA: "https://datacarto.open-datara.fr/wfs"}
#: Emprise (Lambert-93) d'une donnée régionale : hors d'elle, on ne la demande pas.
EMPRISES: Dict[str, Tuple[float, float, float, float]] = {   # emprises du catalogue, en Lambert-93 (+ 5 km)
    cm.ZPPA_BRETAGNE: (76000, 6677000, 415000, 6913000),
    cm.ZPPA_AURA: (642000, 6350000, 1022000, 6626000),
    cm.ZPPA_CVL: (479000, 6599000, 710000, 6828000),
}
#: Filtre appliqué sur le poste : ``(champ, valeurs gardées)`` (le service rend tout, l'emprise est petite).
FILTRES_LOCAUX: Dict[str, Tuple[str, frozenset]] = {
    cm.MONUMENT: ("suptype", frozenset({"ac1"})),            # servitudes : les monuments historiques
    cm.PLU_ZONE: ("typeinf", frozenset({"16"})),             # informations des PLU : l'archéologie
    cm.PLU_POINT: ("typeinf", frozenset({"16"})),
}
#: Filtre côté serveur : on ne télécharge pas toutes les routes pour n'en garder que les ronds-points.
FILTRES = {cm.ROND_POINT: "nature='Rond-point'"}
#: La donnée du Catalogue des flux qui correspond à chaque source : son titre est écrit dans
#: ``contexte_source``, pour que l'utilisateur la retrouve et l'ajoute au projet.
ID_CATALOGUE = {cm.BATIMENT: "batiments", cm.EAU: "surfaces_en_eau", cm.COURS_EAU: "cours_eau",
                cm.HABITATION: "zones_habitation", cm.ROND_POINT: "ctx_ronds_points",
                cm.ROUTE: "routes_chemins", cm.VOIE_FERREE: "ctx_voies_ferrees", cm.TALUS_IGN: "ctx_talus_ign",
                cm.CANALISATION: "ctx_canalisations", cm.MONUMENT: "monuments_historiques",
                cm.PLU_ZONE: "archeo_plu_surfaces", cm.PLU_POINT: "archeo_plu_points", cm.ZPPA_BRETAGNE: "bretagne_zppa",
                cm.ZPPA_AURA: "aura_zppa", cm.ZPPA_CVL: "cvl_zppa"}
CELLULE_M = 10_000.0
PAGE = 5000

Bbox = Tuple[float, float, float, float]


def cellules(emprises: Iterable[Bbox], marge: float = cm.RAYON_RECHERCHE, cote: float = CELLULE_M) -> List[Bbox]:
    """Une boîte par carré de ``cote`` m occupé (grille de ``cote`` m, ordre stable) : l'union des emprises
    des détections élargies de ``marge``, rognée au carré. Aucune détection → aucune requête.

    2026-11-19 (décision de l'utilisateur) : le carré entier n'est plus demandé. Sur le traitement « test »
    (3 × 3 km), il rapportait 9 461 bâtiments et 18 Mo pour 204 objets à portée d'une détection. Un carré
    garde une seule requête (pagination comprise) : jamais plus de requêtes qu'avant ; un traitement qui
    remplit ses carrés ne gagne rien, une zone compacte presque tout."""
    boites: Dict[Tuple[int, int], Bbox] = {}
    for x0, y0, x1, y1 in emprises:
        a, b, c, d = x0 - marge, y0 - marge, x1 + marge, y1 + marge
        for i in range(math.floor(a / cote), math.floor(c / cote) + 1):
            for j in range(math.floor(b / cote), math.floor(d / cote) + 1):
                rx0, ry0 = max(a, i * cote), max(b, j * cote)
                rx1, ry1 = min(c, (i + 1) * cote), min(d, (j + 1) * cote)
                if rx0 >= rx1 or ry0 >= ry1:
                    continue
                v = boites.get((i, j))
                boites[(i, j)] = (rx0, ry0, rx1, ry1) if v is None else (
                    min(v[0], rx0), min(v[1], ry0), max(v[2], rx1), max(v[3], ry1))
    return [boites[k] for k in sorted(boites)]


def url_page(typename: str, bbox: Bbox, debut: int, service: str = SERVICE_WFS, page: int = PAGE,
             filtre: str = "") -> str:
    """GetFeature GeoJSON en Lambert-93 d'une page d'objets d'un carré. ⚠ La Géoplateforme refuse les
    paramètres ``BBOX`` et ``CQL_FILTER`` ensemble : avec un ``filtre``, l'emprise passe dans le filtre."""
    # au mètre près, vers l'extérieur : une boîte serrée ne doit rien perdre à l'arrondi
    x0, y0, x1, y1 = math.floor(bbox[0]), math.floor(bbox[1]), math.ceil(bbox[2]), math.ceil(bbox[3])
    tete = (f"{service}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES={typename}"
            f"&OUTPUTFORMAT=application/json&SRSNAME=EPSG:2154&COUNT={page}&STARTINDEX={debut}"
            # le tri stabilise la pagination ; seule la BD TOPO a ``cleabs``
            + ("&SORTBY=cleabs" if typename.startswith("BDTOPO") else ""))
    if filtre:
        from urllib.parse import quote

        return tete + "&CQL_FILTER=" + quote(f"{filtre} AND BBOX(geometrie,{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f},'EPSG:2154')")
    return tete + f"&BBOX={x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f},EPSG:2154"


#: Essais par page avant d'abandonner (2026-11-18 : un 504 isolé annulait tout le croisement).
ESSAIS_PAGE = 3


def dans_emprise(source: str, boite: Bbox) -> bool:
    """Faux pour une donnée régionale (:data:`EMPRISES`) dont l'emprise ne touche pas la boîte."""
    e = EMPRISES.get(source)
    return not e or not (boite[2] < e[0] or boite[0] > e[2] or boite[3] < e[1] or boite[1] > e[3])


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
    service = SERVICES.get(source, SERVICE_WFS)
    champ, valeurs = FILTRES_LOCAUX.get(source, ("", frozenset()))
    vus, objets = set(), []
    for carre in carres:
        if not dans_emprise(source, carre):
            continue
        debut = 0
        while True:
            if annule():
                return objets
            page = page_lue(url_page(typename, carre, debut, service, filtre=FILTRES.get(source, "")))
            entites = page.get("features") or []
            for f in entites:
                props = f.get("properties") or {}
                cle = props.get("cleabs") or f.get("id")
                if cle in vus or not f.get("geometry"):
                    continue
                if champ and str(props.get(champ)) not in valeurs:
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
    lineaire = cm.est_lineaire(structure)
    for nom, objets in objets_par_source.items():
        if not cm.consulte(nom, structure):
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
    bandes: Dict[int, Any] = {}             # bande de RAYON_LINEAIRE autour d'une ligne longée, calculée une fois
    sortie = []
    for det in detections:
        proches: List[cm.Objet] = []
        longees: Dict[str, list] = {}
        if arbre is not None and det is not None and not det.is_empty:
            d = det if det.is_valid else det.buffer(0)
            aire = d.area or 0.0
            for k in arbre.query(d.buffer(cm.RAYON_RECHERCHE)):
                g = geoms[int(k)]
                distance = d.distance(g)
                if distance > cm.RAYON_RECHERCHE:
                    continue
                nom = meta[int(k)][0]
                if lineaire and nom in cm.LIGNES_LONGEES:
                    # part qui longe la ligne : dans une bande de RAYON_LINEAIRE autour d'elle, tous les tronçons
                    # d'une même donnée réunis (une route est découpée à chaque carrefour)
                    bande = bandes.get(int(k))
                    if bande is None:
                        bande = bandes[int(k)] = g.buffer(cm.RAYON_LINEAIRE)
                    longees.setdefault(nom, []).append((d.intersection(bande).area, distance, int(k), bande))
                    continue
                part = (d.intersection(g).area / aire) if (aire and distance == 0) else 0.0
                proches.append(cm.Objet(nom, meta[int(k)][1], distance, part))
            for nom, liste in longees.items():
                from shapely.ops import unary_union

                principal = max(liste, key=lambda x: (x[0], -x[1]))   # ses attributs nomment la ligne
                part = d.intersection(unary_union([x[3] for x in liste])).area / aire if aire else 0.0
                proches.append(cm.Objet(nom, meta[principal[2]][1], min(x[1] for x in liste), part))
        sortie.append(cm.champs(proches, structure, source, titres, date_iso))
    return sortie


def lire_json_urllib(url: str, proxy: Optional[str] = None, delai: float = 90.0) -> Mapping[str, Any]:
    """Lecteur par défaut (outils de développement, tests de bout en bout) ; le plugin passe le sien."""
    import urllib.request

    poignees = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
    ouvreur = urllib.request.build_opener(*poignees)
    with ouvreur.open(urllib.request.Request(url, headers={"User-Agent": "QGIS"}), timeout=delai) as rep:
        return json.loads(rep.read().decode("utf-8"))
