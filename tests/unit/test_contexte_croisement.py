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


def test_cellules_reduites_a_l_emprise_des_detections():
    """2026-11-19 (décision de l'utilisateur) : on ne télécharge plus le carré de 10 km entier mais, dans
    chaque carré occupé, l'emprise des détections élargie de la marge (sur le traitement « test » :
    9 461 bâtiments reçus, 204 utiles). Jamais plus de requêtes qu'avant : une boîte par carré occupé."""
    assert cc.cellules([]) == []
    assert cc.cellules([(1000, 1000, 2000, 2000)], marge=15) == [(985, 985, 2015, 2015)]
    # deux détections dans le même carré : une seule boîte, leur union
    assert cc.cellules([(1000, 1000, 1010, 1010), (3000, 4000, 3010, 4010)], marge=0) == [(1000, 1000, 3010, 4010)]
    # une détection à 5 m du bord : la marge déborde sur le carré voisin, chaque boîte reste dans son carré
    assert cc.cellules([(9990, 5000, 9995, 5010)], marge=15) == [(9975, 4985, 10000, 5025), (10000, 4985, 10010, 5025)]
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
    assert set(cc.COUCHES) == set(cc.ID_CATALOGUE) == {cm.BATIMENT, cm.EAU, *cm.SOURCES_PONCTUELLES, *cm.SOURCES_LINEAIRES,
                                                         *cm.SOURCES_PATRIMOINE, *cm.SOURCES_A_CALIBRER}


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


# ── 2026-11-19 : les linéaires longent routes, voies ferrées, cours d'eau, talus de l'IGN, canalisations ─────
def test_un_chemin_creux_qui_longe_une_route_coupee_en_deux_troncons():
    from shapely.geometry import LineString

    troncons = {cm.ROUTE: [objet(LineString([(0, 0), (50, 0)]), nature="Chemin"),
                           objet(LineString([(50, 0), (100, 0)]), nature="Chemin")]}
    long_de_la_route = box(0, -2, 100, 2)                    # 4 m de large, 100 m le long du chemin
    (c,) = cc.croiser([long_de_la_route], troncons, "chemins_creux", "s")
    assert c["contexte_info"] == "longe un chemin sur 100 % de sa longueur" and c["contexte_moderne"] is None
    # un parcellaire qui ne fait que traverser la route n'est pas dit la longer
    (x,) = cc.croiser([box(48, -50, 52, 50)], troncons, "parcellaire", "s")
    assert x["contexte_info"] is None


def test_les_lignes_longees_ne_servent_que_les_lineaires():
    from shapely.geometry import LineString

    route = {cm.ROUTE: [objet(LineString([(0, 0), (100, 0)]), nature="Route à 1 chaussée")]}
    assert cc.croiser([box(0, -2, 100, 2)], route, "charbonnieres", "s")[0]["contexte_info"] is None
    assert cc.croiser([box(0, -2, 100, 2)], route, "talus_et_fosses", "s")[0]["contexte_info"] == \
        "longe une route sur 100 % de sa longueur"


def test_filtre_sur_le_poste_et_service_regional_hors_de_sa_region():
    appels = []

    def faux(url):
        appels.append(url)
        return {"features": [{"id": "a", "geometry": mapping(Point(0, 0).buffer(1)), "properties": {"suptype": "ac1"}},
                             {"id": "b", "geometry": mapping(Point(5, 0).buffer(1)), "properties": {"suptype": "ac4"}}]}
    # les servitudes rendent tout : seuls les monuments historiques (ac1) sont gardés, sans tri par cleabs
    objets = cc.telecharger(cm.MONUMENT, [(0, 0, 10, 10)], faux)
    assert len(objets) == 1 and "SORTBY" not in appels[0]
    # la Bretagne n'est pas interrogée pour une zone de Moselle
    assert cc.telecharger(cm.ZPPA_BRETAGNE, [(980000, 6860000, 990000, 6870000)], faux) == [] and len(appels) == 1
    assert cc.telecharger(cm.ZPPA_BRETAGNE, [(350000, 6780000, 351000, 6781000)], faux)
    assert appels[-1].startswith("https://geobretagne.fr/geoserver/drac/ows?")


# ── 2026-11-19 : un carré symbolique de 5 m de l'IGN compte comme un point ──────────────────────────────────
def test_un_parking_symbolique_compte_comme_un_point():
    """Là où l'IGN n'a pas dessiné l'emprise, un parking (ou une station d'épuration) est un carré EXACT de
    5 × 5 m (247 parkings sur 686 dans le corpus). Décision de l'utilisateur : ce carré est un point, son
    centre. Le point DANS la détection l'écarte ; à côté, jusqu'à 15 m, il informe ; un vrai contour écarte
    à 10 %."""
    symbole = {cm.PARKING: [objet(box(100, 100, 105, 105), nature="Parking")]}      # centre (102,5 ; 102,5)
    (dedans,) = cc.croiser([Point(102, 102).buffer(4)], symbole, "charbonnieres", "s")
    assert dedans["contexte_moderne"] == "parking signalé dans la détection (emprise non dessinée par l'IGN)"
    touche = cc.croiser([Point(108, 102).buffer(4)], symbole, "charbonnieres", "s")[0]   # touche le carré, pas son centre
    assert touche["contexte_moderne"] is None
    assert touche["contexte_info"] == "parking signalé à 2 m (emprise non dessinée par l'IGN)"
    pres = cc.croiser([Point(114.5, 102).buffer(4)], symbole, "charbonnieres", "s")[0]
    assert pres["contexte_info"] == "parking signalé à 8 m (emprise non dessinée par l'IGN)"
    assert cc.croiser([Point(130, 102).buffer(4)], symbole, "charbonnieres", "s")[0]["contexte_info"] is None
    vrai = {cm.PARKING: [objet(box(90, 90, 130, 115), nature="Parking")]}
    assert cc.croiser([Point(102, 102).buffer(4)], vrai, "charbonnieres", "s")[0]["contexte_moderne"] ==         "parking recouvrant 100 % de la détection"
    # une structure linéaire n'est jamais écartée, symbole ou non
    assert cc.croiser([Point(102, 102).buffer(4)], symbole, "parcellaire", "s")[0]["contexte_moderne"] is None


def test_seul_un_carre_de_5_m_est_un_symbole():
    assert cc.est_symbole(box(0, 0, 5, 5)) and cc.est_symbole(box(0, 0, 5.05, 5.05))
    assert not cc.est_symbole(box(0, 0, 2.3, 2.3))           # une vraie petite cuve (réservoir du corpus)
    assert not cc.est_symbole(box(0, 0, 5, 8)) and not cc.est_symbole(box(0, 0, 9, 9))
    assert not cc.est_symbole(Point(0, 0).buffer(2.8))       # ≈ 25 m² mais rond : un vrai contour
