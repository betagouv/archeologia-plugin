"""Sources à l'essai du Catalogue des flux (data/fonds_publics/essais.json, 2026-11-12).

Même forme que le catalogue, sans fiche, vignette ni couverture : elles s'explorent avant d'être retenues.
Beaucoup ne valent que pour une région, d'où le filtre « Seulement ce qui couvre la carte affichée ».
"""
from pathlib import Path

from src.app.services import fonds_publics as fp

RACINE = Path(__file__).resolve().parents[2]
CATALOGUE = fp.charger(RACINE / fp.CATALOGUE)[1]
ESSAIS = fp.charger_essais(RACINE / fp.ESSAIS)
PAR_ID = {f.id: f for f in ESSAIS}
CATALOGUE_PAR_ID = {f.id: f for f in CATALOGUE}


def test_les_essais_sont_charges_marques_et_distincts_du_catalogue():
    # 77 au départ ; 40 images puis les 12 vecteurs « Archéologie connue et patrimoine » validés le 2026-11-13.
    assert len(ESSAIS) == 25 and len(PAR_ID) == 25
    assert all(f.essai and f.id.startswith("essai_") and f.theme and f.source for f in ESSAIS)
    assert not {f.id for f in CATALOGUE} & set(PAR_ID)
    assert not any(f.essai for f in CATALOGUE)
    # Les 40 images ont été validées le 2026-11-13 et sont au catalogue, avec leur fiche : restent les vecteurs.
    assert all(f.objets for f in ESSAIS)


def test_les_images_viennent_avant_les_vecteurs_et_chaque_theme_est_d_un_seul_tenant():
    sortes = [f.objets for f in ESSAIS]
    assert sortes == sorted(sortes)
    cles = [(f.objets, f.theme) for f in ESSAIS]
    vus = list(dict.fromkeys(cles))
    assert cles == [c for v in vus for c in cles if c == v]             # pas de thème en deux morceaux


def test_aucune_cle_ni_chemin_de_poste():
    texte = (RACINE / fp.ESSAIS).read_text(encoding="utf-8").lower()
    for interdit in ("apikey", "api_key", "token", "c:/", "c:\\\\", "d:/"):
        assert interdit not in texte


def test_un_fond_wms_donne_une_adresse_wms_et_une_tuile_une_adresse_xyz():
    geologie = CATALOGUE_PAR_ID["geologie_harmonisee"]
    uri = fp.uri_couche("https://data.geopf.fr/wmts", geologie)
    assert uri.startswith("contextualWMSLegend=0&crs=EPSG:3857") and "layers=SCAN_H_GEOL50" in uri
    assert uri.endswith("url=https://geoservices.brgm.fr/geologie")
    photos = CATALOGUE_PAR_ID["photos_2006"]
    assert fp.uri_couche("https://data.geopf.fr/wmts", photos).startswith("type=xyz&url=")
    assert "ORTHOIMAGERY.ORTHOPHOTOS2006-2010" in fp.uri_couche("https://data.geopf.fr/wmts", photos)


def test_un_vecteur_d_un_autre_producteur_est_lu_sur_son_service():
    assert "url='https://geobretagne.fr/geoserver/drac/ows'" in fp.uri_objets(CATALOGUE_PAR_ID["bretagne_sites"])
    assert f"url='{fp.SERVICE_OBJETS}'" in fp.uri_objets(PAR_ID["essai_talus_levees"])


def test_couvre_un_fond_local_seulement_sur_sa_zone():
    bretagne, national = CATALOGUE_PAR_ID["bretagne_sites"], PAR_ID["essai_talus_levees"]
    vosges, rennes = (6.9, 47.7, 7.1, 47.8), (-1.75, 48.05, -1.6, 48.15)
    assert bretagne.local and not national.local
    assert fp.couvre(bretagne, rennes) and not fp.couvre(bretagne, vosges)
    assert fp.couvre(national, vosges) and fp.couvre(national, rennes)
    assert fp.couvre(bretagne, None)                     # carte inconnue : rien n'est masqué
    locaux = [f for f in CATALOGUE + ESSAIS if f.local and f.objets]
    assert len(locaux) >= 15 and all(f.zone for f in locaux)


def test_la_page_range_par_themes_repliables_et_filtre_selon_la_carte():
    src = (RACINE / "src" / "ui" / "fonds_page.py").read_text(encoding="utf-8")
    assert "fp.charger_essais(" in src and "fp.par_theme(self._fonds + self._essais)" in src
    assert 'QCheckBox("Seulement ce qui couvre la carte affichée")' in src and "self._ici.setChecked(True)" in src
    assert "class _Bandeau(QFrame)" in src and "THEMES_OUVERTS = 2" in src
    assert "self._recherche.textChanged.connect(self.appliquer)" in src
    # La petite étiquette « à l'essai », et pas de fiche pour ces sources.
    assert "à l'essai" in src and "if fond.essai:" in src and "self.info.hide()" in src
    assert "corps_fiche_fond(self._fonds," in src
    # La frise pour les images seulement ; une phrase pour les données vectorielles.
    assert "self.frise = None" in src and "QLabel(fond.quoi)" in src


# ── 2026-11-12 : rangement par thème, catalogue et essais mêlés ──────────────────────────────────────────────
TOUS = CATALOGUE + ESSAIS


def test_chaque_source_a_un_theme_connu_et_chaque_vecteur_sa_phrase():
    assert all(f.theme in fp.THEMES for f in TOUS)
    assert all(f.quoi for f in TOUS if f.objets) and not any(f.quoi for f in TOUS if not f.objets)


def test_par_theme_les_images_d_abord_dans_l_ordre_des_themes():
    sections = fp.par_theme(TOUS)
    assert [(t, o) for t, o, _m in sections] == [
        ("Cartes anciennes", False), ("Photos aériennes", False), ("Relief, sol et géologie", False),
        ("Archéologie connue et patrimoine", True), ("Bâti, routes et eau", True),
        ("Relief, sous-sol et mines", True), ("Aménagements modernes", True)]
    assert sum(len(m) for _t, _o, m in sections) == len(TOUS) == 96   # 6 fonds de Strasbourg retirés le 2026-11-18
    for _t, objets, membres in sections:
        assert all(f.objets == objets for f in membres)


def test_par_theme_les_images_suivent_le_temps_et_le_catalogue_precede_les_essais():
    sections = {(t, o): m for t, o, m in fp.par_theme(TOUS)}
    photos = sections[("Photos aériennes", False)]
    debuts = [f.debut for f in photos]
    assert debuts == sorted(debuts) and photos[0].debut == 1947                     # Calvados 1947 ouvre la série
    archeo = sections[("Archéologie connue et patrimoine", True)]
    assert len(archeo) == 13 and not any(f.essai for f in archeo)                    # tout le thème est validé
    assert {f.essai for f in sections[("Bâti, routes et eau", True)]} == {True, False}   # catalogue et essais mêlés
    cartes = sections[("Cartes anciennes", False)]
    assert cartes[0].id == "cassini" and "terrier_corse_1" in [f.id for f in cartes[:3]]
    bati = sections[("Bâti, routes et eau", True)]
    assert [f.essai for f in bati] == sorted(f.essai for f in bati)                  # le catalogue d'abord
    sans_date = sections[("Relief, sol et géologie", False)]
    assert [f.debut is None for f in sans_date] == sorted(f.debut is None for f in sans_date)   # sans date à la fin


def test_un_theme_inconnu_passe_a_la_fin():
    from dataclasses import replace
    etranger = replace(CATALOGUE[0], id="x", theme="Autre chose")
    assert fp.par_theme([etranger] + CATALOGUE[:2])[-1][0] == "Autre chose"


def test_la_recherche_porte_sur_le_titre_la_provenance_la_zone_et_la_phrase():
    texte = fp.texte_recherche(CATALOGUE_PAR_ID["bretagne_sites"])
    for mot in ("sites archéologiques", "drac bretagne", "bretagne", "datation"):
        assert mot in texte
    assert "brgm" in fp.texte_recherche(PAR_ID["essai_forages"])


def test_un_fichier_absent_ne_casse_rien(tmp_path):
    assert fp.charger_essais(tmp_path / "absent.json") == []
