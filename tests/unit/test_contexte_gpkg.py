"""Écriture du contexte moderne dans de vrais GeoPackages (réseau simulé)."""
import sqlite3

import pytest

gpd = pytest.importorskip("geopandas")
pytest.importorskip("pyogrio")
from shapely.geometry import box, mapping  # noqa: E402

from src.app.services import contexte_gpkg as cg  # noqa: E402

HANGAR = {"cleabs": "B1", "nature": "Industriel, agricole ou commercial", "usage_1": "Agricole",
          "etat_de_l_objet": "En service"}
RETENUE = {"cleabs": "E1", "nature": "Retenue", "origine": "Artificielle", "persistance": "Permanent"}
X0, Y0 = 987000, 6865000          # Fénétrange, Lambert-93


def _gpkg(chemin, couche, geoms, **champs):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    gdf = gpd.GeoDataFrame({"fiabilite": ["Probable"] * len(geoms), "confidence": [0.7] * len(geoms), **champs},
                           geometry=geoms, crs="EPSG:2154")
    gdf.to_file(chemin, layer=couche, driver="GPKG", engine="pyogrio")


def _faux_wfs(appels):
    def lire(url):
        appels.append(url)
        if "STARTINDEX=0" not in url:
            return {"features": []}
        if "TYPENAMES=BDTOPO_V3:batiment&" in url:
            return {"features": [{"geometry": mapping(box(X0 + 5, Y0 + 5, X0 + 20, Y0 + 20)), "properties": HANGAR}]}
        if "surface_hydrographique" in url:
            return {"features": [{"geometry": mapping(box(X0 + 200, Y0, X0 + 400, Y0 + 200)), "properties": RETENUE}]}
        assert "lieu_dit_non_habite" not in url          # plus téléchargés (2026-11-18)
        return {"features": []}
    return lire


@pytest.fixture
def run(tmp_path):
    det = tmp_path / "livrable" / "detections"
    _gpkg(det / "enclos" / "enclos.gpkg", "Enclos",
          [box(X0, Y0, X0 + 40, Y0 + 40), box(X0 + 210, Y0 + 10, X0 + 250, Y0 + 50), box(X0 + 5000, Y0, X0 + 5040, Y0 + 40)])
    _gpkg(det / "talus_et_fosses" / "talus_et_fosses.gpkg", "Talus et fossés · talus",
          [box(X0 + 210, Y0 + 60, X0 + 260, Y0 + 70)])
    _gpkg(det / "regroupement" / "regroupement.gpkg", "zones", [box(X0, Y0, X0 + 500, Y0 + 500)], nb_detect=[12])
    _gpkg(det / "_technique" / "brut.gpkg", "brut", [box(X0, Y0, X0 + 1, Y0 + 1)])
    return det


def _lignes(gpkg, couche):
    with sqlite3.connect(gpkg) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(f'SELECT * FROM "{couche}" ORDER BY fid')]


def test_les_couches_de_synthese_et_techniques_sont_laissees(run):
    noms = [(p.parent.name, c) for p, c in cg.couches_de_detections(run)]
    assert noms == [("enclos", "Enclos"), ("talus_et_fosses", "Talus et fossés · talus")]


def test_marquer_ecrit_les_cinq_champs_sans_toucher_au_reste(run):
    appels = []
    bilan = cg.marquer(run, _faux_wfs(appels), aujourd_hui="2026-11-11")
    enclos = _lignes(run / "enclos" / "enclos.gpkg", "Enclos")
    assert [e["contexte_moderne"] for e in enclos] == ["bâtiment agricole recouvrant 14 % de la détection", "étang (retenue) recouvrant 100 % de la détection", None]
    assert enclos[0]["contexte_part"] == 14 and enclos[0]["contexte_dist_m"] == 0         # 225 m² sur 1 600 m²
    assert enclos[2]["contexte_info"] is None and enclos[2]["contexte_moderne"] is None   # rien à proximité
    assert enclos[0]["contexte_source"] == "Bâtiments (BD TOPO, IGN), lue le 2026-11-11"
    assert enclos[1]["contexte_source"] == "Surfaces en eau et mares (BD TOPO, IGN), lue le 2026-11-11"
    assert [e["fiabilite"] for e in enclos] == ["Probable"] * 3 and enclos[0]["confidence"] == 0.7
    # la même retenue informe sous un talus : la digue d'étang est un vrai talus
    (talus,) = _lignes(run / "talus_et_fosses" / "talus_et_fosses.gpkg", "Talus et fossés · talus")
    assert talus["contexte_moderne"] is None and talus["contexte_info"] == "étang (retenue) recouvrant 100 % de la détection"
    # la synthèse n'a pas reçu les champs
    assert "contexte_moderne" not in _lignes(run / "regroupement" / "regroupement.gpkg", "zones")[0]
    # un talus ne consulte que les bâtiments et l'eau, et le dit quand il ne trouve rien
    assert talus["contexte_source"] == "Surfaces en eau et mares (BD TOPO, IGN), lue le 2026-11-11"
    assert (bilan.total, bilan.marquees, bilan.informees) == (4, 2, 1)   # plus de lieu-dit (2026-11-18)
    assert bilan.par_structure == {"enclos": (3, 2, 0), "talus_et_fosses": (1, 0, 1)}
    assert bilan.source == ("Bâtiments · Surfaces en eau et mares · Cours d'eau · Zones d'habitation · "
                            "Ronds-points (BD TOPO, IGN), lue le 2026-11-11")
    assert bilan.phrase.startswith("Contexte moderne : sur 4 détections, 2 en contexte moderne")
    # une seule passe par donnée et par carré de 10 km occupé
    assert len(appels) == 5 * 2          # cinq données depuis le retrait des lieux-dits (2026-11-18)


def test_marquer_deux_fois_ne_duplique_pas_les_champs(run):
    cg.marquer(run, _faux_wfs([]), aujourd_hui="2026-11-11")
    cg.marquer(run, _faux_wfs([]), aujourd_hui="2026-11-12")
    enclos = _lignes(run / "enclos" / "enclos.gpkg", "Enclos")
    assert enclos[0]["contexte_source"].endswith("2026-11-12")
    assert sum(1 for k in enclos[0] if k.startswith("contexte_")) == 5


def test_l_index_spatial_reste_coherent_apres_ecriture(run):
    cg.marquer(run, _faux_wfs([]), aujourd_hui="2026-11-11")
    with sqlite3.connect(run / "enclos" / "enclos.gpkg") as con:
        rtree = con.execute('SELECT COUNT(*), MIN(minx), MAX(maxx) FROM "rtree_Enclos_geom"').fetchone()
    assert rtree == (3, X0, X0 + 5040)
    gdf = gpd.read_file(run / "enclos" / "enclos.gpkg", layer="Enclos", engine="pyogrio")
    assert len(gdf) == 3 and gdf.geometry.is_valid.all() and "contexte_moderne" in gdf.columns


def test_enveloppe_d_une_geometrie_gpkg():
    assert cg._enveloppe(None)[0] is True and cg._enveloppe(b"xx")[0] is True


def test_reseau_injoignable_rien_n_est_ecrit(run):
    def panne(url):
        raise OSError("hors ligne")
    bilan = cg.marquer(run, panne)
    assert bilan.motif.startswith("Contexte moderne non vérifié : la BD TOPO de l'IGN est injoignable")
    assert "contexte_moderne" not in _lignes(run / "enclos" / "enclos.gpkg", "Enclos")[0]


def test_hors_lambert_93_on_ne_croise_pas(run):
    bilan = cg.marquer(run, _faux_wfs([]), crs="EPSG:27700")
    assert "ne couvre que la France" in bilan.motif and "EPSG:27700" in bilan.motif


def test_annule_pendant_le_telechargement(run):
    bilan = cg.marquer(run, _faux_wfs([]), annule=lambda: True)
    assert bilan.motif == "Contexte moderne non vérifié : traitement annulé."


def test_sans_detection_rien_a_faire(tmp_path):
    assert cg.marquer(tmp_path, _faux_wfs([])).total == 0
    assert cg.marquer(tmp_path, _faux_wfs([])).phrase == ""


def test_les_titres_sont_ceux_du_catalogue_des_flux():
    """contexte_source nomme la donnée telle que la page « Fonds de carte » l'affiche."""
    from src.app.services import fonds_publics as fp
    from pathlib import Path

    racine = Path(__file__).resolve().parents[2]
    _s, fonds = fp.charger(racine / fp.CATALOGUE)
    from src.app.services import contexte_croisement as cc

    titres = {f.id: f.titre for _g, f, _v in fp.couches_contexte(fonds)}
    titres.update({f.id: f.titre for f in fonds if f.objets})
    assert cg.titres_catalogue() == {source: titres[ident] for source, ident in cc.ID_CATALOGUE.items()}
    assert cg.titres_catalogue() == cg.TITRES_PAR_DEFAUT
    # 2026-11-18 : le rond-point se nomme comme la couche que le bouton ajoute, plus « Routes et chemins »
    assert cg.titres_catalogue()["rond_point"] == "Ronds-points"


# ── 2026-11-13 : les objets téléchargés sont gardés dans le livrable, le bouton les lit sans réseau ────────
def test_les_objets_telecharges_sont_gardes_dans_le_livrable(run):
    import pyogrio

    from src.app.services import contexte_croisement as cc

    cg.marquer(run, _faux_wfs([]), aujourd_hui="2026-11-13")
    cg.marquer(run, _faux_wfs([]), aujourd_hui="2026-11-13")          # un second traitement remplace le fichier
    gpkg = cg.chemin_contexte(run)
    assert gpkg == run.parent / "contexte" / "contexte_moderne.gpkg" and gpkg.is_file()
    # une couche par donnée qui a des objets, nommée comme la source du croisement
    assert {str(n) for n, _t in pyogrio.list_layers(gpkg)} == {"batiment", "eau"}
    bati = gpd.read_file(gpkg, layer="batiment", engine="pyogrio")
    assert len(bati) == 1 and bati.crs.to_epsg() == 2154 and bati.loc[0, "usage_1"] == "Agricole"
    assert bati.geometry[0].bounds == (X0 + 5, Y0 + 5, X0 + 20, Y0 + 20)
    # le fichier n'est pas pris pour une couche de détections
    assert [(p.parent.name, c) for p, c in cg.couches_de_detections(run)] == [
        ("enclos", "Enclos"), ("talus_et_fosses", "Talus et fossés · talus")]
    # chaque donnée du croisement a sa couche du bouton « Ajouter le contexte moderne »
    assert set(cg.COUCHE_PAR_FOND.values()) == set(cc.COUCHES)


def test_sans_objet_ou_sans_reseau_pas_de_fichier_local(run):
    def panne(url):
        raise OSError("hors ligne")
    cg.marquer(run, panne)
    assert not cg.chemin_contexte(run).exists()
    cg.marquer(run, lambda url: {"features": []})
    assert not cg.chemin_contexte(run).exists()


def test_le_journal_cite_les_six_donnees_lues(run):
    """2026-11-18 : le journal en citait cinq (il oubliait les cours d'eau) pour six lues."""
    dit = []
    cg.marquer(run, _faux_wfs([]), journal=dit.append)
    lecture = next(m for m in dit if "lecture de la BD TOPO" in m)
    for mot in ("bâtiments", "eau", "cours d'eau", "zones d'habitation", "ronds-points"):
        assert mot in lecture, mot


def test_une_comparaison_ne_rend_pas_lineaire_une_structure_ponctuelle(tmp_path):
    """2026-11-18 : ``est_lineaire`` lisait aussi le modèle qualifiant une comparaison A/B (« --lineaires_…»,
    « — Structures linéaires… ») : une structure ponctuelle n'aurait jamais été écartée."""
    from src.app.services import contexte_moderne as cm

    det = tmp_path / "detections"
    gpkg = det / "charbonnieres--lineaires_seg_v3_1" / "charbonnieres--lineaires_seg_v3_1.gpkg"
    structure = cg._structure(det, gpkg, "Charbonnières — Structures linéaires 3 classes (LD)")
    assert not cm.est_lineaire(structure)
    talus = det / "talus_fosse" / "talus_fosse.gpkg"
    assert cm.est_lineaire(cg._structure(det, talus, "Talus et fossés"))


def test_un_fichier_local_impossible_a_ecrire_ne_bloque_pas_le_marquage(run, monkeypatch):
    def refus(det_dir, objets):
        raise PermissionError("verrouillé")
    monkeypatch.setattr(cg, "garder_objets", refus)
    dit = []
    bilan = cg.marquer(run, _faux_wfs([]), journal=dit.append)
    assert bilan.marquees == 2 and any("non enregistrées" in m for m in dit)
