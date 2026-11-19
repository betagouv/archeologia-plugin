"""Catégorie « Écartées » et petits enclos (décisions de l'utilisateur, 2026-11-19).

- La catégorie grise « Contexte moderne » s'appelle « Écartées » : elle reçoit les détections écartées par le
  contexte moderne ET celles écartées par l'aire minimale de leur structure.
- Le filtre d'aire ne supprime plus : il remplit ``ecart_taille`` (« surface de 32 m², sous le minimum de
  50 m² ») ; la détection reste dans le GeoPackage, grisée, et compte dans le bilan parmi les écartées.
- Défaut : 50 m² pour les enclos et les enclos circulaires, porté par le catalogue des structures.
"""
import json
import sqlite3
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

import pipeline.cv.conversion_shp as cs
from app.services import bilan_fiabilite as bf
from app.services import contexte_moderne as cm
from app.services import fiabilite as fb
from app.services import model_orchestrator as mo

RACINE = Path(__file__).resolve().parents[2]


def _gpkg(tmp_path):
    p = tmp_path / "enclos.gpkg"
    gdf = gpd.GeoDataFrame({"fiabilite": ["Probable", "Douteux"], "confidence": [0.8, 0.4]},
                           geometry=[box(0, 0, 40, 40), box(100, 100, 104, 108)], crs="EPSG:2154")
    gdf.to_file(p, layer="Enclos", driver="GPKG")
    return p


def test_le_filtre_d_aire_marque_au_lieu_de_supprimer(tmp_path):
    p = _gpkg(tmp_path)
    cs._filter_gpkg_by_min_area([str(p)], min_area_m2=50)
    g = gpd.read_file(p, layer="Enclos")
    assert len(g) == 2                                      # rien n'est supprimé
    petit = g[g.geometry.area < 50].iloc[0]
    assert petit[cm.CHAMP_ECART_TAILLE] == "surface de 32 m², sous le minimum de 50 m²"
    assert not g[g.geometry.area >= 50].iloc[0][cm.CHAMP_ECART_TAILLE]


def test_le_bilan_compte_les_petits_parmi_les_ecartees(tmp_path):
    p = _gpkg(tmp_path)
    fb.sidecar_path(p).write_text(json.dumps({"Enclos": {"effectifs": {"Probable": 1, "Douteux": 1}}}),
                                  encoding="utf-8")
    cs._filter_gpkg_by_min_area([str(p)], min_area_m2=50)
    fb.recompter_effectifs(p)                               # appelé après les filtres d'aire
    entree = json.loads(fb.sidecar_path(p).read_text(encoding="utf-8"))["Enclos"]
    assert entree["ecartes"] == {"Douteux": 1}


def test_categorie_ecartees_et_ses_deux_champs():
    assert cm.CATEGORIE_LEGENDE == "Écartées"
    assert bf.LIBELLE_ECARTEES == "écartées"
    deux = cm.expression_legende("fiabilite", ("contexte_moderne", cm.CHAMP_ECART_TAILLE))
    assert "\"contexte_moderne\"" in deux and f"\"{cm.CHAMP_ECART_TAILLE}\"" in deux and "'Écartées'" in deux
    seul = cm.expression_legende("fiabilite", (cm.CHAMP_ECART_TAILLE,))
    assert "contexte_moderne" not in seul          # un champ absent de la couche masquerait tout


def test_la_raison_de_taille_est_dans_l_infobulle():
    html = fb.maptip_html([], "enclos_fr_seg_ld_v1", structure="Enclos")
    assert cm.CHAMP_ECART_TAILLE in html


def test_defaut_50_m2_pour_les_enclos_dans_le_catalogue():
    cat = {e.id: e for e in mo.load_entities_catalog(RACINE / "data" / "entities_catalog.json")}
    assert cat["enclos"].min_area_m2 == 50 and cat["enclos_circulaire"].min_area_m2 == 50
    assert cat["parcellaire"].min_area_m2 is None
