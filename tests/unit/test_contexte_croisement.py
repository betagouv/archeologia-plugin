"""Croisement géométrique des détections avec la BD TOPO (sans réseau : objets en mémoire)."""
import pytest

pytest.importorskip("shapely")
from shapely.geometry import Point, box, mapping  # noqa: E402

from src.app.services import contexte_croisement as cc  # noqa: E402
from src.app.services import contexte_moderne as cm  # noqa: E402

HANGAR = {"nature": "Industriel, agricole ou commercial", "usage_1": "Agricole", "etat_de_l_objet": "En service"}
MARE = {"nature": "Mare", "origine": "Naturelle non aménagée", "persistance": "Permanent"}
RETENUE = {"nature": "Retenue", "origine": "Artificielle", "persistance": "Permanent"}


def objet(geom, **props):
    return {"geometry": mapping(geom), "properties": props}


def test_cellules_calees_sur_la_grille_et_elargies_du_rayon():
    assert cc.cellules([]) == []
    assert cc.cellules([(1000, 1000, 2000, 2000)]) == [(0.0, 0.0, 10000.0, 10000.0)]
    # une détection à 5 m du bord : le rayon de recherche (15 m) déborde sur la cellule voisine
    assert cc.cellules([(9990, 5000, 9995, 5010)]) == [(0.0, 0.0, 10000.0, 10000.0), (10000.0, 0.0, 20000.0, 10000.0)]
    assert len(cc.cellules([(942500, 6731500, 1003500, 6768500)])) == 7 * 4      # Vosges : 7 × 4 carrés


def test_url_d_une_page():
    u = cc.url_page("BDTOPO_V3:batiment", (0, 0, 10000, 10000), 5000)
    assert u.startswith("https://data.geopf.fr/wfs/ows?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature")
    assert "TYPENAMES=BDTOPO_V3:batiment" in u and "SRSNAME=EPSG:2154" in u and "STARTINDEX=5000" in u
    assert "BBOX=0,0,10000,10000,EPSG:2154" in u and "CQL_FILTER" not in u and "COUNT=5000" in u


def test_telecharger_pagine_dedoublonne_et_reduit_les_attributs():
    pages = {}

    def faux(url):
        pages[url] = pages.get(url, 0) + 1
        debut = int(url.split("STARTINDEX=")[1].split("&")[0])
        if "BBOX=0,0" in url:
            n = cc.PAGE if debut == 0 else 2      # 5 000 puis 2 : deux pages
            return {"features": [{"geometry": mapping(Point(i, 0).buffer(1)),
                                  "properties": {"cleabs": f"B{debut + i}", "nature": "x", "hauteur": 7}}
                                 for i in range(n)]}
        return {"features": [{"geometry": mapping(Point(0, 0).buffer(1)), "properties": {"cleabs": "B0"}}]}  # doublon

    objets = cc.telecharger(cm.BATIMENT, [(0, 0, 10000, 10000), (10000, 0, 20000, 10000)], faux)
    assert len(objets) == cc.PAGE + 2 and len(pages) == 3
    assert set(objets[0]["properties"]) == {"nature", "usage_1", "etat_de_l_objet", "construction_legere"}


def test_telecharger_reessaie_une_page_avant_d_abandonner():
    """2026-11-18 : un seul 504 de la Géoplateforme annulait tout le croisement (mesuré : 2 échecs sur ~130
    requêtes). Une page est redemandée ; au-delà des essais, l'erreur remonte comme avant."""
    appels = []

    def capricieux(url):
        appels.append(url)
        if len(appels) < 3:
            raise OSError("HTTP 504")
        return {"features": []}

    assert cc.telecharger(cm.EAU, [(0, 0, 1, 1)], capricieux, pause=lambda s: None) == []
    assert len(appels) == 3

    def toujours_en_panne(url):
        raise OSError("HTTP 504")

    with pytest.raises(OSError):
        cc.telecharger(cm.EAU, [(0, 0, 1, 1)], toujours_en_panne, pause=lambda s: None)


def test_telecharger_s_arrete_si_le_traitement_est_annule():
    assert cc.telecharger(cm.EAU, [(0, 0, 1, 1)], lambda u: {"features": []}, annule=lambda: True) == []


def test_croiser_bati_sur_la_detection_et_mare_proche():
    enclos = box(0, 0, 40, 40)
    objets = {cm.BATIMENT: [objet(box(10, 10, 30, 30), **HANGAR)],
              cm.EAU: [objet(box(48, 0, 58, 10), **MARE)]}
    (c,) = cc.croiser([enclos], objets, "enclos", "BD TOPO (IGN), lue le 2026-11-11")
    assert c["contexte_moderne"] == "bâtiment agricole recouvrant 25 % de la détection"
    assert c["contexte_info"] == "mare à 8 m (origine naturelle)"
    assert c["contexte_dist_m"] == 0 and c["contexte_part"] == 25          # 400 m² sur 1 600 m²
    assert c["contexte_source"] == "BD TOPO (IGN), lue le 2026-11-11"


def test_url_filtree_l_emprise_passe_dans_le_filtre():
    u = cc.url_page("BDTOPO_V3:troncon_de_route", (0, 0, 10000, 10000), 0, filtre="nature='Rond-point'")
    assert "&BBOX=" not in u and "CQL_FILTER=nature%3D%27Rond-point%27%20AND%20BBOX%28geometrie%2C0%2C0%2C10000%2C10000" in u
    assert cc.FILTRES == {cm.ROND_POINT: "nature='Rond-point'"}
    assert set(cc.COUCHES) == set(cc.ID_CATALOGUE) == {cm.BATIMENT, cm.EAU, *cm.SOURCES_PONCTUELLES}


def test_croiser_les_troncons_d_un_rond_point_sont_refermes_en_disque():
    from shapely.geometry import LineString

    anneau = list(Point(100, 100).buffer(17).exterior.coords)
    moities = [LineString(anneau[:len(anneau) // 2 + 1]), LineString(anneau[len(anneau) // 2:])]
    objets = {cm.ROND_POINT: [objet(m, nature="Rond-point") for m in moities]}
    ilot, loin = cc.croiser([Point(100, 100).buffer(12), Point(160, 100).buffer(12)], objets, "enclos_circulaires", "s")
    assert ilot["contexte_moderne"] == "rond-point recouvrant 100 % de la détection" and ilot["contexte_part"] == 100
    assert loin["contexte_moderne"] is None and loin["contexte_info"] is None
    # un talus sur le même rond-point n'est pas concerné (les linéaires viendront plus tard)
    assert cc.croiser([Point(100, 100).buffer(12)], objets, "talus_et_fosses", "s")[0]["contexte_moderne"] is None


def test_croiser_cours_d_eau_et_zone_d_habitation():
    from shapely.geometry import LineString

    objets = {cm.COURS_EAU: [objet(LineString([(-50, 20), (90, 20)]), nature="Ecoulement naturel", persistance="Permanent"),
                             objet(LineString([(-50, 110), (90, 110)]), nature="Ecoulement naturel", persistance="Permanent")],
              cm.HABITATION: [objet(box(200, 0, 300, 100), nature="Lieu-dit habité", toponyme="le Hameau")]}
    traverse, longe, hameau = cc.croiser([box(0, 0, 40, 40), box(0, 60, 40, 100), box(210, 10, 250, 50)], objets, "enclos",
                                         "s", {cm.COURS_EAU: "Cours d'eau",
                                               cm.HABITATION: "Zones d'habitation"}, "2026-11-12")
    assert traverse["contexte_info"] == "cours d'eau traversant la détection"
    assert traverse["contexte_source"] == "Cours d'eau (BD TOPO, IGN), lue le 2026-11-12"
    assert longe["contexte_info"] == "cours d'eau à 10 m"
    assert hameau["contexte_moderne"] is None                       # une zone d'habitation ne grise plus (2026-11-13)
    assert hameau["contexte_info"] == "dans la zone d'habitation « le Hameau »" and hameau["contexte_part"] == 100


def test_croiser_hors_rayon_rien_sauf_la_source():
    (c,) = cc.croiser([box(0, 0, 10, 10)], {cm.BATIMENT: [objet(box(30, 0, 40, 10), **HANGAR)]}, "enclos", "s")
    assert c == {"contexte_moderne": None, "contexte_info": None, "contexte_dist_m": None,
                 "contexte_part": None, "contexte_source": "s"}


def test_croiser_la_structure_change_l_effet_d_une_retenue():
    objets = {cm.EAU: [objet(box(0, 0, 100, 100), **RETENUE)]}
    enclos, talus = cc.croiser([box(10, 10, 20, 20)] * 2, objets, "enclos", "s")[0], \
        cc.croiser([box(10, 10, 20, 20)], objets, "talus_et_fosses", "s")[0]
    assert enclos["contexte_moderne"] == "étang (retenue) recouvrant 100 % de la détection" and enclos["contexte_part"] == 100
    assert talus["contexte_moderne"] is None and talus["contexte_info"] == "étang (retenue) recouvrant 100 % de la détection"


def test_croiser_garde_l_ordre_et_tolere_les_geometries_vides_ou_invalides():
    from shapely.geometry import Polygon

    noeud = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])                 # nœud papillon, invalide
    res = cc.croiser([box(0, 0, 5, 5), None, Polygon(), noeud],
                     {cm.BATIMENT: [objet(box(0, 0, 10, 10), **HANGAR), {"geometry": None}]}, "enclos", "s")
    assert len(res) == 4
    assert res[0]["contexte_moderne"].startswith("bâtiment agricole")
    assert res[1]["contexte_moderne"] is None and res[1]["contexte_source"] == "s"
    assert res[2]["contexte_moderne"] is None
    assert res[3]["contexte_moderne"].startswith("bâtiment agricole")


def test_croiser_sans_aucun_objet():
    assert cc.croiser([box(0, 0, 1, 1)], {}, "enclos", "s")[0]["contexte_source"] == "s"
