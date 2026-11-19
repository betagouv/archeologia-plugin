"""Un même objet détecté sous deux structures : les deux sont gardés, chacun nomme l'autre."""
import gc
import sqlite3

import pytest

gpd = pytest.importorskip("geopandas")
pytest.importorskip("pyogrio")
from shapely.geometry import Point, box  # noqa: E402

from src.app.services import doublons_structures as ds  # noqa: E402

X0, Y0 = 995600, 6746250


def _gpkg(chemin, couche, geoms, classe, fiabilite="Probable", pct=68, **champs):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    n = len(geoms)
    gdf = gpd.GeoDataFrame({"model_pred": [classe] * n, "fiabilite": [fiabilite] * n,
                            "fiabilite_pct": [float(pct)] * n, **champs}, geometry=geoms, crs="EPSG:2154")
    gdf.to_file(chemin, layer=couche, driver="GPKG", engine="pyogrio")


def _valeurs(gpkg, couche):
    with sqlite3.connect(gpkg) as con:
        return [r[0] for r in con.execute(f'SELECT "{ds.CHAMP}" FROM "{couche}" ORDER BY fid')]


@pytest.fixture
def det(tmp_path):
    d = tmp_path / "livrable" / "detections"
    # la charbonnière du test : une boîte, et la dépression en disque presque superposée
    _gpkg(d / "charbonnieres" / "charbonnieres.gpkg", "Charbonnières",
          [box(X0, Y0, X0 + 18, Y0 + 18), box(X0 + 500, Y0, X0 + 518, Y0 + 18)], "charbonniere")
    _gpkg(d / "depressions" / "depressions.gpkg", "Dépressions circulaires grandes",
          [Point(X0 + 9, Y0 + 9).buffer(8), Point(X0 + 900, Y0).buffer(8)], "depression_circulaire_grande", pct=71)
    return d


def test_les_deux_objets_superposes_se_nomment_et_rien_n_est_supprime(det):
    assert ds.marquer(det) == 2
    assert _valeurs(det / "charbonnieres" / "charbonnieres.gpkg", "Charbonnières") == [
        "Dépressions circulaires grandes (probable, 71 %)", None]
    assert _valeurs(det / "depressions" / "depressions.gpkg", "Dépressions circulaires grandes") == [
        "Charbonnières (probable, 68 %)", None]


def test_un_petit_objet_dans_un_grand_n_est_pas_un_doublon(det):
    # un enclos qui contient la charbonnière, un talus qui la traverse : deux objets distincts
    _gpkg(det / "enclos" / "enclos.gpkg", "Enclos", [box(X0 - 30, Y0 - 30, X0 + 60, Y0 + 60)], "enclos")
    _gpkg(det / "talus" / "talus.gpkg", "Talus", [box(X0 - 100, Y0 + 7, X0 + 100, Y0 + 11)], "talus")
    ds.marquer(det)
    assert _valeurs(det / "enclos" / "enclos.gpkg", "Enclos") == [None]
    assert _valeurs(det / "talus" / "talus.gpkg", "Talus") == [None]


def test_la_meme_classe_vue_par_deux_modeles_n_est_pas_marquee(det):
    # comparaison A/B ou détections sources d'un regroupement : même classe, pas une confusion
    _gpkg(det / "charbonnieres--autre" / "charbonnieres--autre.gpkg", "Charbonnières — autre",
          [box(X0, Y0, X0 + 18, Y0 + 18)], "charbonniere")
    ds.marquer(det)
    assert _valeurs(det / "charbonnieres--autre" / "charbonnieres--autre.gpkg", "Charbonnières — autre") == [
        "Dépressions circulaires grandes (probable, 71 %)"]
    assert _valeurs(det / "charbonnieres" / "charbonnieres.gpkg", "Charbonnières")[0] == \
        "Dépressions circulaires grandes (probable, 71 %)"


def test_un_nouveau_passage_efface_une_marque_perimee(det):
    ds.marquer(det)
    gc.collect()        # Windows : une connexion de lecture pas encore ramassée verrouille le fichier
    (det / "depressions" / "depressions.gpkg").unlink()
    assert ds.marquer(det) == 0
    assert _valeurs(det / "charbonnieres" / "charbonnieres.gpkg", "Charbonnières") == [None, None]


def test_libelle_sans_fiabilite():
    assert ds.libelle("Cratères", None, None) == "Cratères"
    assert ds.libelle("Cratères", "Très probable", 91.0) == "Cratères (très probable, 91 %)"
