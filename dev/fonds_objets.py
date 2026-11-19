"""Ajoute au catalogue des fonds publics ses **données vectorielles** et rend leurs images.

Un vecteur n'est pas une tuile : ses objets sont chargés en direct par QGIS (WFS de la Géoplateforme,
limité à la zone affichée) et dessinés en contours par-dessus le relief. Cet outil :

- écrit leurs entrées dans `data/fonds_publics/fonds.json`, **après** les images (la page les range
  dans leur propre section) ;
- rend leur vignette et leur aperçu : contours au style du plugin, posés sur la photo aérienne ;
- mesure leur couverture sur la France (`couverture.json`) : une requête de comptage par case de la
  grille des fonds, dans le système de coordonnées du service.

    C:/OSGeo4W/bin/python-qgis.bat dev/fonds_objets.py      # Python de QGIS (rendu, reprojection), réseau
    C:/OSGeo4W/bin/python-qgis.bat dev/fonds_objets.py cours_eau lieux_dits    # ces vecteurs seulement (les
                                                            # autres gardent leur entrée, leurs images, leur couverture)

Liste validée par l'utilisateur le 2026-11-11 : bâtiments, surfaces en eau (validés d'abord), puis
routes et chemins, parcelles cadastrales, zones d'activité, monuments historiques, état-major vectorisé.
Ajoutés le 2026-11-12 avec le croisement du contexte moderne, qui les nomme dans ``contexte_source`` : zones
d'habitation, cours d'eau, lieux-dits (des points, dessinés avec leur nom).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
from src.app.services import fonds_publics as fp  # noqa: E402

SORTIE = RACINE / fp.CATALOGUE.parent
FENETRANGE = (7.0205, 48.8475)

#: Libellés des codes d'occupation du sol de la BD CARTO État-major (descriptif de contenu et de livraison,
#: version 1.0, octobre 2026, § 6.1.2 ; 37 valeurs simples et leurs combinaisons).
THEMES_EM = {
    "EM1.1": "Village", "EM1.2": "Bâtiment", "EM1.3": "Cimetière", "EM2.1": "Jardin", "EM2.2": "Parc de château",
    "EM3.1": "Mines ou carrières", "EM4.1": "Cultures", "EM5.1": "Vigne", "EM6.1": "Verger",
    "EM6.2": "Verger sur culture", "EM6.3": "Semis irrégulier d'arbres", "EM6.4": "Bocage", "EM7.1": "Prairie",
    "EM7.2": "Essart", "EM8.1": "Pâquis, pâture", "EM8.2": "Pelouses et prairies pâturées", "EM8.3": "Prés-bois",
    "EM8.4": "Chaume", "EM8.5": "Lande", "EM8.6": "Terre vaine", "EM9.1": "Forêt", "EM10.1": "Étang, lac",
    "EM10.2": "Retenue d'eau", "EM10.3": "Rivière", "EM10.4": "Canal", "EM10.5": "Mer, océan", "EM11.1": "Marais",
    "EM11.2": "Marais salant", "EM11.3": "Estran", "EM11.4": "Pré salé", "EM12.1": "Plage", "EM12.2": "Dune",
    "EM13.1": "Gravière", "EM14.1": "Rocher, falaise, éboulis", "EM15.1": "Glacier", "EM16.1": "Nature inconnue",
    # combinaisons (dans les deux ordres)
    "EM1.2EM16.1": "Bâtiment religieux", "EM6.3EM1.2": "Bâtiments et arbres isolés",
    "EM4.1EM8.4": "Culture et chaume", "EM4.1EM11.1": "Culture marécageuse", "EM4.1EM8.2": "Cultures",
    "EM9.1EM12.2": "Dune boisée", "EM8.1EM12.2": "Dune pâturée", "EM9.1EM11.1": "Forêt marécageuse",
    "EM8.1EM9.1": "Forêt pâturée", "EM8.1EM13.1": "Gravière pâturée", "EM6.4EM8.1": "Pâquis, pâture bocagers",
    "EM8.1EM11.1": "Pâquis, pâture marécageux", "EM8.1EM6.2": "Pâquis, pâture plantés d'arbres",
    "EM4.1EM10.4": "Plantation sur zone drainée", "EM6.3EM7.1": "Prairie avec arbres",
    "EM7.1EM10.4": "Prairie avec canaux", "EM6.4EM7.1": "Prairie bocagère", "EM7.1EM11.1": "Prairie marécageuse",
    "EM6.2EM7.1": "Prairie plantée d'arbres", "EM11.4EM12.2": "Pré salé", "EM4.1EM6.3": "Semis irrégulier d'arbres",
    "EM6.1EM7.1": "Verger planté sur prairie", "EM4.1EM6.1": "Verger sur culture", "EM4.1EM6.2": "Verger sur culture",
    "EM5.1EM12.2": "Vigne sur dunes",
}


def _symetriser(d):
    out = dict(d)
    for k, v in d.items():
        codes = re.findall(r"EM\d{1,2}\.\d{1,2}", k)
        if len(codes) == 2:
            out.setdefault(codes[1] + codes[0], v)
    return out


def _expression_em() -> str:
    paires = ", ".join(f"'{k}', '{v.replace(chr(39), chr(39) * 2)}'" for k, v in sorted(_symetriser(THEMES_EM).items()))
    return f"coalesce(map_get(map({paires}), replace(\"theme\", ' ', '')), \"theme\")"


#: Un vecteur : identifiant, couche WFS, titre, époque, début, fin, géométrie, couleur, expression lue au clic,
#: système du service, filtre (côté serveur), colonne géométrique (pour le comptage filtré), lieu et côté de l'aperçu.
OBJETS = [
    dict(id="batiments", typename="BDTOPO_V3:batiment", titre="Bâtiments", couleur="#c2410c", attribut="nature",
         lieu=FENETRANGE, nom_lieu="Fénétrange, Moselle", cote=500),
    dict(id="zones_habitation", typename="BDTOPO_V3:zone_d_habitation", titre="Zones d'habitation",
         couleur="#a8323e", expression="\"nature\" || coalesce(' · ' || \"toponyme\", '')",
         lieu=FENETRANGE, nom_lieu="Fénétrange, Moselle", cote=3000),
    dict(id="surfaces_en_eau", typename="BDTOPO_V3:surface_hydrographique", titre="Surfaces en eau et mares",
         couleur="#1d6fb8", attribut="nature", lieu=(6.9177, 48.8267), nom_lieu="étangs près de Fénétrange, Moselle",
         cote=3000),
    dict(id="cours_eau", typename="BDTOPO_V3:troncon_hydrographique", titre="Cours d'eau", geometrie="ligne",
         couleur="#0e8fa3",
         expression="\"nature\" || coalesce(' · ' || \"cpx_toponyme_de_cours_d_eau\", '') || ' · ' || lower(\"persistance\")",
         lieu=(6.9177, 48.8267), nom_lieu="étangs près de Fénétrange, Moselle", cote=3000),
    dict(id="routes_chemins", typename="BDTOPO_V3:troncon_de_route", titre="Routes et chemins", geometrie="ligne",
         couleur="#7a4b1d", attribut="nature", lieu=(7.005, 48.86), nom_lieu="Fénétrange, Moselle", cote=1500),
    dict(id="lieux_dits", typename="BDTOPO_V3:lieu_dit_non_habite", titre="Lieux-dits", geometrie="point",
         couleur="#5b4a8a", attribut="toponyme", lieu=FENETRANGE, nom_lieu="autour de Fénétrange, Moselle", cote=5000),
    dict(id="parcelles", typename="CADASTRALPARCELS.PARCELLAIRE_EXPRESS:parcelle",
         titre="Parcelles, avec leurs références", couleur="#7b3fa0",
         expression="'Section ' || \"section\" || ' · parcelle ' || ltrim(\"numero\", '0') || ' · ' || \"nom_com\"",
         lieu=FENETRANGE, nom_lieu="Fénétrange, Moselle", cote=600, source="IGN, DGFiP"),
    dict(id="zones_activite", typename="BDTOPO_V3:zone_d_activite_ou_d_interet", titre="Zones d'activité et d'intérêt",
         couleur="#b0306a", expression="\"nature\" || coalesce(' · ' || \"toponyme\", '')",
         lieu=FENETRANGE, nom_lieu="Fénétrange, Moselle", cote=1200),
    dict(id="monuments_historiques", typename="wfs_sup:generateur_sup_s", titre="Monuments historiques",
         couleur="#c81d25", expression="coalesce(\"nomsuplitt\", \"nomgen\")", srs="EPSG:4326",
         filtre="\"suptype\" = 'ac1'", cql="suptype='ac1'", colonne="the_geom", lieu=None,
         nom_lieu="", cote=400, source="Ministère de la Culture, Géoportail de l'urbanisme"),
    dict(id="etat_major_vecteur", typename="BDCARTO_ETAT-MAJOR.NIVEAU4:c_1_1_ocs_ancien",
         titre="Occupation du sol vers 1850", epoque="1820-1866", debut=1820, fin=1866, couleur="#3d7a3a",
         expression=_expression_em(), lieu=FENETRANGE, nom_lieu="Fénétrange, Moselle", cote=2000),
    # ── 2026-11-13 : les 12 données « Archéologie connue et patrimoine » validées par l'utilisateur ──
    dict(id='archeo_plu_surfaces', typename='wfs_du:info_surf', titre='Archéologie des PLU (zones)', couleur='#b2182b', attribut='libelle', filtre='"typeinf" = \'16\'', cql="typeinf='16'", colonne='the_geom', geometrie='surface', srs='EPSG:4326', lieu=(-3.0763, 47.5885), nom_lieu='Carnac, Morbihan', cote=600, source="Collectivités, Géoportail de l'urbanisme", theme='Archéologie connue et patrimoine', quoi="Sites archéologiques recensés et zones de présomption reportés dans les plans d'urbanisme"),
    dict(id='archeo_plu_points', typename='wfs_du:info_pct', titre='Archéologie des PLU (points)', couleur='#2166ac', attribut='libelle', filtre='"typeinf" = \'16\'', cql="typeinf='16'", colonne='the_geom', geometrie='point', srs='EPSG:4326', lieu=(1.9295, 48.6525), nom_lieu='La Celle-les-Bordes, Yvelines', cote=1500, source="Collectivités, Géoportail de l'urbanisme", theme='Archéologie connue et patrimoine', quoi="Sites archéologiques reportés dans les plans d'urbanisme"),
    dict(id='bretagne_sites', typename='drac:site', titre='Sites archéologiques connus (Bretagne)', couleur='#1b7837', expression='coalesce("NATURE", "STRUCTURE", \'site\') || \' · \' || "DEBUT" || if("FIN" <> "DEBUT", \' à \' || "FIN", \'\') || \' · \' || "NOM"', service_objets='https://geobretagne.fr/geoserver/drac/ows', zone='Bretagne', geometrie='point', srs='EPSG:2154', emprise=(-5.1401, 47.2801, -1.0248, 48.8929), lieu=(-2.3381, 48.2983), nom_lieu="Bois de Bougueneuf, Rouillac, Côtes-d'Armor", cote=1500, source='DRAC Bretagne', theme='Archéologie connue et patrimoine', quoi='Le site déjà connu, sa nature et sa datation'),
    dict(id='bretagne_zppa', typename='drac:bretagne_zppa', titre='Zones de présomption (Bretagne)', couleur='#762a83', expression='"COMMUNE" || \' · zone \' || "N_ZONE" || \' · arrêté \' || "NUM_ARRETE" || \' du \' || "DATE_ARRET"', service_objets='https://geobretagne.fr/geoserver/drac/ows', zone='Bretagne', geometrie='surface', srs='EPSG:2154', emprise=(-5.1914, 47.1661, -0.9689, 48.99), lieu=(-2.3381, 48.2983), nom_lieu="Rouillac, Côtes-d'Armor", cote=2000, source='DRAC Bretagne', theme='Archéologie connue et patrimoine', quoi="Là où l'État présume des vestiges, et par quel arrêté"),
    dict(id='bretagne_operations', typename='drac:operations_archeologiques', titre='Opérations archéologiques (Bretagne)', couleur='#b35806', expression='"NATURE_OPE" || \' \' || "DATE" || \' · \' || "TITRE"', service_objets='https://geobretagne.fr/geoserver/drac/ows', zone='Bretagne', geometrie='surface', srs='EPSG:2154', emprise=(-5.0855, 47.2974, -1.0185, 48.8646), lieu=(-2.521, 48.4621), nom_lieu="Rue de Penthièvre, Lamballe-Armor, Côtes-d'Armor", cote=600, source='DRAC Bretagne', theme='Archéologie connue et patrimoine', quoi='Les emprises déjà diagnostiquées ou fouillées'),
    dict(id='bretagne_voies', typename='drac:reseau_viaire', titre='Réseau viaire ancien (Bretagne)', couleur='#01665e', expression='"NOM" || \' · \' || "DEBUT" || \' à \' || "FIN"', service_objets='https://geobretagne.fr/geoserver/drac/ows', zone='Bretagne', geometrie='surface', srs='EPSG:2154', emprise=(-4.7721, 47.4917, -1.0165, 48.7857), lieu=(-4.1201, 48.1742), nom_lieu='Voie Carhaix/Douarnenez à Cast, Finistère', cote=1500, source='DRAC Bretagne', theme='Archéologie connue et patrimoine', quoi='Voies de la protohistoire au Moyen Âge'),
    dict(id='bretagne_monuments', typename='drac:immeubles_proteges_mh', titre='Monuments historiques, notices (Bretagne)', couleur='#c51b7d', expression='"titre_editorial_de_la_notice" || coalesce(\' · \' || "format_abrege_du_siecle_de_construction", \'\') || coalesce(\' · \' || "typologie_de_la_protection", \'\')', service_objets='https://geobretagne.fr/geoserver/drac/ows', zone='Bretagne', geometrie='point', srs='EPSG:2154', emprise=(-5.1509, 47.2875, -1.0433, 49.1051), lieu=(-3.9537, 47.8971), nom_lieu='Tertre tumulaire de Kerleven, La Forêt-Fouesnant, Finistère', cote=800, source='DRAC Bretagne', theme='Archéologie connue et patrimoine', quoi="Le nom, le siècle et la protection de l'édifice"),
    dict(id='aura_zppa', typename='ms:n_atlaspatrimoine_zppa_s_r84', titre='Zones de présomption (Auvergne-Rhône-Alpes)', couleur='#e66101', expression='"comm_nom" || \' · \' || coalesce(nullif("scientif", \'\'), "prot_objet")', service_objets='https://datacarto.open-datara.fr/wfs', zone='Auvergne-Rhône-Alpes', geometrie='surface', srs='EPSG:2154', emprise=(2.33, 44.29, 6.97, 46.62), lieu=(4.67506, 44.73236), nom_lieu='Chomérac, Ardèche', cote=1200, source='DRAC Auvergne-Rhône-Alpes, Atlas des patrimoines', theme='Archéologie connue et patrimoine', quoi="Là où l'État présume des vestiges, et lesquels"),
    dict(id='cvl_zppa', typename='zppa_cvl_executoire_2025_gpkg_06-03-2026_wfs:zppa_cvl_executoire_2025', titre='Zones de présomption (Centre-Val de Loire)', couleur='#b2182b', expression='"communes" || \' · zone \' || "zone" || \' · \' || "seuil"', zone='Centre-Val de Loire', geometrie='surface', srs='EPSG:2154', emprise=(0.18, 46.54, 3.07, 48.47), lieu=(0.23724, 47.15642), nom_lieu='Chinon, Indre-et-Loire', cote=3500, source='DRAC Centre-Val de Loire', theme='Archéologie connue et patrimoine', quoi='Les zones en vigueur et leur seuil'),
    dict(id='hdf_monuments', typename='geo2france:immeuble_merimee', titre='Monuments historiques, notices (Hauts-de-France)', couleur='#2166ac', attribut='titre_editorial_de_la_notice', service_objets='https://www.geo2france.fr/geoserver/ows', zone='Hauts-de-France', geometrie='point', srs='EPSG:2154', emprise=(1.38, 48.87, 4.21, 51.06), lieu=(2.51957, 49.3612), nom_lieu='Catenoy, Oise', cote=800, source='Ministère de la Culture, Géo2France', theme='Archéologie connue et patrimoine', quoi="Le nom de l'édifice protégé"),
    dict(id='sites_classes', typename='sites_metropole_gpkg_26-01-2026_wfs:STE_Metropole', titre='Sites inscrits et classés', couleur='#1b7837', expression='"typesite" || \' · \' || "nomgen"', filtre='"typesite" IN (\'Site inscrit\', \'Site classé\')', cql="typesite IN ('Site inscrit', 'Site classé')", colonne='geom', geometrie='surface', srs='EPSG:2154', lieu=(2.51815, 46.68731), nom_lieu='La Groutte, Cher', cote=800, source='Ministère de la Transition écologique', theme='Archéologie connue et patrimoine', quoi='Le patrimoine paysager protégé'),
    dict(id='sites_patrimoniaux', typename='wfs_sup:generateur_sup_s', titre='Sites patrimoniaux remarquables', couleur='#762a83', expression='coalesce(nullif("nomsuplitt", \'\'), "nomgen")', filtre='"suptype" = \'ac4\'', cql="suptype='ac4'", colonne='the_geom', geometrie='surface', srs='EPSG:4326', lieu=(0.16649, 45.26354), nom_lieu='Aubeterre-sur-Dronne, Charente', cote=3200, source="Ministère de la Culture, Géoportail de l'urbanisme", theme='Archéologie connue et patrimoine', quoi='Les ensembles urbains, ruraux et paysagers protégés'),
]
#: Thème de la page et phrase « ce qu'on y lit » des vecteurs d'origine.
THEME_QUOI = {
    'batiments': ('Bâti, routes et eau', 'Un bâtiment sur la détection ou tout contre'),
    'zones_habitation': ('Bâti, routes et eau', 'Hameaux, bourgs et lotissements'),
    'surfaces_en_eau': ('Bâti, routes et eau', 'Mare, étang, bassin ou retenue'),
    'cours_eau': ('Bâti, routes et eau', 'Ruisseaux, canaux et fossés'),
    'routes_chemins': ('Bâti, routes et eau', 'Routes, chemins et ronds-points'),
    'lieux_dits': ('Bâti, routes et eau', 'Le nom du lieu, souvent parlant'),
    'parcelles': ('Bâti, routes et eau', 'Section et numéro, pour une déclaration'),
    'zones_activite': ('Bâti, routes et eau', 'Carrières, usines, campings, stations'),
    'monuments_historiques': ('Archéologie connue et patrimoine', 'Le monument protégé lui-même, avec son nom'),
    'etat_major_vecteur': ('Bâti, routes et eau', 'Bois, prés, vignes et labours vers 1850'),
}
for _o in OBJETS:
    if _o["id"] in THEME_QUOI:
        _o["theme"], _o["quoi"] = THEME_QUOI[_o["id"]]


def _entree(o) -> dict:
    entree = {"id": o["id"], "couche": o["typename"], "typename": o["typename"], "titre": o["titre"],
              "epoque": o.get("epoque", "aujourd'hui"), "debut": o.get("debut", 2020), "fin": o.get("fin"),
              "format": "", "style": "", "zmin": 0, "zmax": 19, "detail_m": 0, "repere": False,
              "couleur": o["couleur"], "attribut": o.get("attribut", ""), "expression": o.get("expression", ""),
              "geometrie": o.get("geometrie", "surface"), "srs": o.get("srs", "EPSG:2154"), "filtre": o.get("filtre", ""),
              "vignette": f"vignettes/{o['id']}.jpg", "apercu": f"apercus/{o['id']}.jpg",
              "lieu_apercu": o["nom_lieu"], "source": o.get("source", "IGN"),
              "theme": o["theme"], "quoi": o["quoi"]}
    for cle in ("service_objets", "zone", "emprise"):       # donnée d'un autre service, ou d'une seule région
        if o.get(cle):
            entree[cle] = list(o[cle]) if cle == "emprise" else o[cle]
    return entree


def _fond(o, entree) -> fp.Fond:
    return fp.Fond(id=o["id"], couche=o["typename"], titre=o["titre"], epoque=entree["epoque"],
                   debut=entree["debut"], fin=entree["fin"], format="", style="", zmin=0, zmax=19,
                   typename=o["typename"], couleur=o["couleur"], attribut=entree["attribut"],
                   expression=entree["expression"], geometrie=entree["geometrie"], srs=entree["srs"],
                   filtre=entree["filtre"], service_objets=o.get("service_objets", ""))


def _couche(fond: fp.Fond):
    """La couche WFS, ouverte comme le fait la page (``fonds_page._couche_objets``) : version 2.0.0, puis
    1.1.0 (GéoBretagne, Géo2France), puis le lecteur de GDAL, qui lit la couche entière (ZPPA d'AURA)."""
    from qgis.core import QgsVectorLayer

    couche = QgsVectorLayer(fp.uri_objets(fond), fond.titre, "WFS")
    if not couche.isValid():
        couche = QgsVectorLayer(fp.uri_objets(fond, version="1.1.0"), fond.titre, "WFS")
    if not couche.isValid() and fond.service_objets:
        couche = QgsVectorLayer(f"WFS:{fond.service_objets}|layername={fond.typename}", fond.titre, "ogr")
    assert couche.isValid(), fond.id
    return couche


def _premier_monument(app, fond) -> tuple:
    """Un monument historique réel près de Fénétrange, pour l'aperçu (la couche est clairsemée)."""
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeatureRequest, QgsProject,
                           QgsRectangle, QgsVectorLayer)

    couche = QgsVectorLayer(fp.uri_objets(fond), "mh", "WFS")
    couche.setSubsetString(fond.filtre)
    for f in couche.getFeatures(QgsFeatureRequest().setFilterRect(QgsRectangle(6.95, 48.75, 7.15, 48.95))):
        nom = f["nomsuplitt"] or f["nomgen"]
        c = f.geometry().centroid().asPoint()
        vers = QgsCoordinateTransform(couche.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
        p = vers.transform(c)
        return (p.x(), p.y()), f"{nom}, Moselle" if nom else "Moselle"
    return FENETRANGE, "Fénétrange, Moselle"


def _rendre(fond: fp.Fond, service: str, photo: fp.Fond, lieu, cote_m: int, cote_px: int, sortie: Path) -> int:
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeatureRequest, QgsFillSymbol,
                           QgsLineSymbol, QgsMapRendererSequentialJob, QgsMapSettings, QgsMarkerSymbol, QgsPointXY,
                           QgsProject, QgsRasterLayer, QgsRectangle, QgsRuleBasedRenderer, QgsSingleSymbolRenderer)
    from qgis.PyQt.QtCore import QSize

    l93 = QgsCoordinateReferenceSystem("EPSG:2154")
    centre = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), l93, QgsProject.instance()).transform(
        QgsPointXY(*lieu))
    emprise = QgsRectangle(centre.x() - cote_m / 2, centre.y() - cote_m / 2, centre.x() + cote_m / 2,
                           centre.y() + cote_m / 2)
    fond_photo = QgsRasterLayer(fp.uri_couche(service, photo), "photo", "wms")
    couche = _couche(fond)
    assert fond_photo.isValid(), "photo"
    if fond.geometrie == "ligne":
        symbole = QgsLineSymbol.createSimple({"line_color": fond.couleur, "line_width": "0.9"})
    elif fond.geometrie == "point":
        symbole = QgsMarkerSymbol.createSimple({"name": "circle", "color": fond.couleur, "outline_color": "#ffffff",
                                                "size": "3.2"})
    else:
        symbole = QgsFillSymbol.createSimple({"style": "no", "outline_color": fond.couleur, "outline_width": "0.9"})
    vers = QgsCoordinateTransform(l93, couche.crs(), QgsProject.instance())
    demande = QgsFeatureRequest().setFilterRect(vers.transformBoundingBox(emprise))
    if fond.filtre:
        # Comme la page : le filtre est une règle de dessin, jamais envoyé au service (QGIS 3.44 ne reçoit
        # rien d'un filtre envoyé aux couches des plans d'urbanisme, mesuré le 2026-11-13 ; QGIS 4 si).
        racine = QgsRuleBasedRenderer.Rule(None)
        racine.appendChild(QgsRuleBasedRenderer.Rule(symbole, filterExp=fond.filtre))
        couche.setRenderer(QgsRuleBasedRenderer(racine))
        demande.setFilterExpression(fond.filtre)
    else:
        couche.setRenderer(QgsSingleSymbolRenderer(symbole))
    n = sum(1 for _ in couche.getFeatures(demande))
    ms = QgsMapSettings()
    ms.setLayers([couche, fond_photo])
    ms.setDestinationCrs(l93)
    ms.setExtent(emprise)
    ms.setOutputSize(QSize(cote_px, cote_px))
    job = QgsMapRendererSequentialJob(ms)
    job.start()
    job.waitForFinished()
    job.renderedImage().save(str(sortie), "JPG", 85)
    return n


def _couverture(o: dict, cases_l93: list) -> list:
    """La grille des fonds (zoom 10) : ``1`` si le service compte au moins un objet dans la case."""
    def compte(bbox) -> bool:
        x0, y0, x1, y1 = bbox
        if o.get("cql"):
            filtre = f"{o['cql']} AND BBOX({o['colonne']},{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f},'EPSG:2154')"
            u = (f"{fp.SERVICE_OBJETS}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&RESULTTYPE=hits&TYPENAMES="
                 f"{o['typename']}&CQL_FILTER={urllib.parse.quote(filtre)}")
        else:
            u = (f"{fp.SERVICE_OBJETS}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&RESULTTYPE=hits&TYPENAMES="
                 f"{o['typename']}&BBOX={x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f},EPSG:2154")
        for essai in range(5):
            try:
                x = urllib.request.urlopen(u, timeout=90).read().decode("utf-8", "ignore")
                m = re.search(r'numberMatched="(\d+)"', x)
                if m:
                    return int(m.group(1)) > 0
            except OSError:
                pass
            time.sleep(2 * (essai + 1))         # le service refuse par moments les rafales de requêtes
        return None

    # 6 requêtes à la fois (24 en faisaient refuser une partie), puis une passe lente sur les échecs.
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(compte, cases_l93))
    for i, r in enumerate(res):
        if r is None:
            res[i] = compte(cases_l93[i])
    echecs = sum(1 for r in res if r is None)
    if echecs:
        print(f"  {o['id']} : {echecs} case(s) sans réponse, comptées vides", flush=True)
    return [bool(r) for r in res]


def _couverture_par_lecture(fond: fp.Fond, zoom: int) -> set:
    """Les cases de la grille que touche au moins un objet, en lisant la couche entière : pour une donnée
    régionale d'un autre service, qui ne sait pas toujours compter par emprise."""
    import math

    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeatureRequest, QgsProject

    couche = _couche(fond)
    vers = QgsCoordinateTransform(couche.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
    n = 2 ** zoom

    def case(lon, lat):
        return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

    demande = QgsFeatureRequest().setNoAttributes()
    if fond.filtre:
        demande = QgsFeatureRequest().setFilterExpression(fond.filtre)
    touchees = set()
    for f in couche.getFeatures(demande):
        g = f.geometry()
        if g.isEmpty():
            continue
        try:
            r = vers.transformBoundingBox(g.boundingBox())
        except Exception:  # noqa: BLE001 — une géométrie hors du domaine de la projection
            continue
        x0, y1 = case(r.xMinimum(), r.yMinimum())
        x1, y0 = case(r.xMaximum(), r.yMaximum())
        touchees.update((x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1))
    return touchees


def main() -> int:
    from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject,
                           QgsRectangle)

    app = QgsApplication([], False)
    app.initQgis()
    brut = json.loads((SORTIE / "fonds.json").read_text(encoding="utf-8"))
    images = [f for f in brut["fonds"] if not f.get("typename")]
    service, fonds = fp.charger(SORTIE / "fonds.json")
    photo = next(f for f in fonds if f.id == "photos")
    couv = json.loads((RACINE / fp.COUVERTURE).read_text(encoding="utf-8"))
    vers_l93 = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), QgsCoordinateReferenceSystem("EPSG:2154"),
                                      QgsProject.instance())
    toutes = [(couv["x0"] + i, couv["y0"] + j) for j in range(couv["rangees"]) for i in range(couv["colonnes"])]
    en_france = {c for c in toutes if couv["fonds"]["photos"]["lignes"][c[1] - couv["y0"]][c[0] - couv["x0"]] == "1"}
    cases = [c for c in toutes if c in en_france]
    bboxes = []
    for c in cases:
        o, s, e, n = fp.bornes_case(couv["zoom"], *c)
        r = vers_l93.transformBoundingBox(QgsRectangle(o, s, e, n))
        bboxes.append((r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()))
    entrees = []
    seuls, anciennes = set(sys.argv[1:]), {f["id"]: f for f in brut["fonds"] if f.get("typename")}
    assert seuls <= {o["id"] for o in OBJETS}, seuls
    for o in OBJETS:
        entree = _entree(o)
        if seuls and o["id"] not in seuls:
            entrees.append(anciennes[o["id"]])           # entrée, images et couverture déjà faites
            continue
        fond = _fond(o, entree)
        lieu = o["lieu"]
        if lieu is None:
            lieu, entree["lieu_apercu"] = _premier_monument(app, fond)
        n = _rendre(fond, service, photo, lieu, o["cote"], 512, SORTIE / entree["apercu"])
        _rendre(fond, service, photo, lieu, o["cote"] // 2, 128, SORTIE / entree["vignette"])
        if o.get("service_objets"):
            touchees = _couverture_par_lecture(fond, couv["zoom"])
            oui = {c: c in touchees for c in cases}
        else:
            oui = dict(zip(cases, _couverture(o, bboxes)))
        lignes = ["".join("1" if oui.get((couv["x0"] + i, couv["y0"] + j)) else "0" for i in range(couv["colonnes"]))
                  for j in range(couv["rangees"])]
        couv["fonds"][o["id"]] = {"cases": sum(oui.values()), "lignes": lignes}
        print(f"{o['id']:22s} {n:5d} objets dans l'aperçu | couverture {sum(oui.values())} / {len(cases)}", flush=True)
        entrees.append(entree)
    brut["fonds"] = images + entrees                     # les vecteurs après les images : leur section
    (SORTIE / "fonds.json").write_text(json.dumps(brut, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    couv["fonds"] = {k: v for k, v in couv["fonds"].items()
                     if k in {f["id"] for f in brut["fonds"]}}
    (RACINE / fp.COUVERTURE).write_text(json.dumps(couv, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(len(entrees), "vecteurs écrits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
