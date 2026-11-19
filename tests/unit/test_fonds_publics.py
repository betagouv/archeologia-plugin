"""Fonds de carte publics de l'onglet « Catalogue des flux » (logique pure + catalogue livré)."""
from pathlib import Path

import pytest

from src.app.services import fonds_publics as fp

RACINE = Path(__file__).resolve().parents[2]
SERVICE, FONDS = fp.charger(RACINE / fp.CATALOGUE)
PAR_ID = {f.id: f for f in FONDS}


VECTEURS = ["batiments", "zones_habitation", "surfaces_en_eau", "cours_eau", "routes_chemins", "lieux_dits",
            "parcelles", "zones_activite", "monuments_historiques", "etat_major_vecteur",
            # 2026-11-13 : le thème « Archéologie connue et patrimoine », validé en entier
            "archeo_plu_surfaces", "archeo_plu_points", "bretagne_sites", "bretagne_zppa", "bretagne_operations",
            "bretagne_voies", "bretagne_monuments", "aura_zppa", "cvl_zppa", "hdf_monuments", "sites_classes",
            "sites_patrimoniaux"]


def test_le_catalogue_livre_porte_49_images_et_22_vecteurs():
    """15 images d'origine, plus les 40 « à l'essai » validées le 2026-11-13."""
    assert SERVICE == "https://data.geopf.fr/wmts"
    assert len(FONDS) == 71 and len(PAR_ID) == 71   # 6 fonds de Strasbourg retirés le 2026-11-18
    assert sum(1 for f in FONDS if not f.objets) == 49
    assert [f.id for f in FONDS if f.objets] == VECTEURS


def test_les_vecteurs_viennent_apres_les_images_dans_leur_section():
    sortes = [f.objets for f in FONDS]
    assert sortes == sorted(sortes)                      # toutes les images, puis tous les objets


def test_chaque_vecteur_dit_ce_que_montre_le_clic():
    for ident in VECTEURS:
        f = PAR_ID[ident]
        assert f.affichage and f.couleur.startswith("#") and f.geometrie in ("surface", "ligne", "point"), ident
    assert PAR_ID["routes_chemins"].geometrie == "ligne" and PAR_ID["cours_eau"].geometrie == "ligne"
    assert PAR_ID["lieux_dits"].geometrie == "point" and PAR_ID["lieux_dits"].affichage == '"toponyme"'
    assert PAR_ID["parcelles"].affichage.startswith("'Section ' ||")
    mh = PAR_ID["monuments_historiques"]
    assert mh.srs == "EPSG:4326" and mh.filtre == '"suptype" = \'ac1\'' and "srsname='EPSG:4326'" in fp.uri_objets(mh)
    em = PAR_ID["etat_major_vecteur"]
    assert em.debut == 1820 and em.fin == 1866
    assert "'EM7.1', 'Prairie'" in em.affichage and "'EM9.1', 'Forêt'" in em.affichage
    assert "'EM7.1EM6.3', 'Prairie avec arbres'" in em.affichage and "'EM6.3EM7.1', 'Prairie avec arbres'" in em.affichage
    assert PAR_ID["batiments"].affichage == '"nature"'


def test_ordre_des_groupes_dans_qgis():
    assert (fp.GROUPE_OBJETS, fp.GROUPE_REPERES, fp.GROUPE_FONDS) == ("Données vectorielles", "Repères", "Fonds de carte")
    assert {"cassini", "etat_major", "photos_1980", "plan_ign", "cadastre", "geologie"} <= set(PAR_ID)


def test_le_catalogue_est_public_sans_cle_ni_chemin_de_poste():
    texte = (RACINE / fp.CATALOGUE).read_text(encoding="utf-8").lower()
    for interdit in ("apikey", "key=", "c:\\", "c:/", "users"):
        assert interdit not in texte


@pytest.mark.parametrize("fond", FONDS, ids=lambda f: f.id)
def test_chaque_fond_a_sa_vignette_et_des_zooms_coherents(fond):
    assert (RACINE / fp.CATALOGUE.parent / fond.vignette).is_file()
    assert 0 <= fond.zmin < fond.zmax <= 21
    assert fond.objets or (fond.format and fond.style)       # une image a son format, un vecteur sa couche
    assert fond.titre and fond.epoque and fond.source


def test_douze_fonds_portent_leur_legende_officielle_livree():
    """Les autres n'ont à la Géoplateforme que l'image générique LEGEND.jpg, ou pas de légende : rien à montrer."""
    avec = {f.id for f in FONDS if f.legende}
    assert avec == {"cassini", "forets_anciennes", "carte_1950", "lidar_classes", "photos", "plan_ign", "cadastre",
                    "cosia", "courbes", "inrap", "ocsge_couverture", "ocsge_usage"}
    for f in FONDS:
        if f.legende:
            assert (RACINE / fp.CATALOGUE.parent / f.legende).is_file()


def test_ordre_chronologique_les_sans_date_a_la_fin():
    debuts = [f.debut for f in FONDS if not f.objets]
    dates = [d for d in debuts if d is not None]
    assert dates == sorted(dates)
    assert debuts[len(dates):] == [None] * (len(debuts) - len(dates))


def test_les_reperes_sont_les_fonds_transparents():
    assert {f.id for f in FONDS if f.repere} == {"cadastre", "forets_anciennes", "courbes", "inrap"}


def test_un_fond_local_porte_sa_zone_et_son_emprise():
    verdun = PAR_ID["verdun_1916"]
    assert verdun.local and verdun.zone == "Meuse"
    locaux = {f.id for f in FONDS if f.local}
    assert {"verdun_1916", "etat_major_10", "strasbourg_photos_1964", "photos_calvados_1955", "terrier_corse_1",
            "carte_allemande_voies_ferrees_1917", "paris_1906"} <= locaux and len(locaux) == 28
    # L'emprise d'un fond de Strasbourg est celle que le service annonce, pas un rectangle approché.
    assert PAR_ID["strasbourg_photos_1964"].emprise == (7.6191, 48.4756, 7.8755, 48.7047)
    assert PAR_ID["strasbourg_photos_1964"].wms == "https://www.datagrandest.fr/geoserver/ows"
    assert PAR_ID["strasbourg_photos_1964"].detail_m == 0          # un service WMS n'annonce pas sa finesse
    assert all(f.zone for f in FONDS if f.local)


def test_les_fonds_retires_du_service_de_strasbourg_ne_reviennent_pas():
    """2026-11-18 (dev/controle_flux.py) : six couches de l'Eurométropole ont disparu du service de
    DataGrandEst (LayerNotDefined) sans adresse de remplacement ; elles sont retirées du catalogue,
    de ses fiches, de sa couverture, de ses images et du générateur dev/fonds_publics.py."""
    retires = {"strasbourg_relief_1725", "strasbourg_1750", "strasbourg_souabe_1818",
               "strasbourg_cadastre_1840", "strasbourg_cadastre_1895", "strasbourg_photos_1932"}
    assert not retires & set(PAR_ID)
    donnees = RACINE / "data" / "fonds_publics"
    for nom in ("fiches.json", "couverture.json"):
        assert not any(i in (donnees / nom).read_text(encoding="utf-8") for i in retires), nom
    assert not any((donnees / d / f"{i}.jpg").exists() for d in ("vignettes", "apercus") for i in retires)
    assert not any(i in (RACINE / "dev" / "fonds_publics.py").read_text(encoding="utf-8") for i in retires)


def test_nom_de_couche_l_epoque_d_abord():
    assert PAR_ID["etat_major"].nom_couche == "1820-1866 · Carte de l'état-major"


def test_uri_en_tuiles_directes_seuls_esperluette_et_egal_encodes():
    """QGIS 3.44 (Qt5) ne décode pas une adresse encodée en entier : aucune tuile, aucune erreur."""
    uri = fp.uri_couche(SERVICE, PAR_ID["etat_major"])
    assert uri.startswith("type=xyz&url=https://data.geopf.fr/wmts?SERVICE%3DWMTS%26REQUEST%3DGetTile")
    assert "LAYER%3DGEOGRAPHICALGRIDSYSTEMS.ETATMAJOR40" in uri
    assert "TILEMATRIX%3D{z}%26TILEROW%3D{y}%26TILECOL%3D{x}" in uri
    assert uri.endswith("&zmin=6&zmax=15")
    adresse = uri.split("&url=")[1].split("&zmin=")[0]
    assert "&" not in adresse and "=" not in adresse
    assert "%3A" not in uri and "%2F" not in uri and "%7B" not in uri


def test_un_vecteur_se_charge_en_direct_sur_la_zone_affichee():
    bati = PAR_ID["batiments"]
    assert bati.objets and not bati.repere and bati.couleur.startswith("#") and bati.attribut == "nature"
    uri = fp.uri_objets(bati)
    assert "typename='BDTOPO_V3:batiment'" in uri and "url='https://data.geopf.fr/wfs/ows'" in uri
    assert "restrictToRequestBBOX='1'" in uri and "pagingEnabled='true'" in uri and "srsname='EPSG:2154'" in uri
    assert PAR_ID["surfaces_en_eau"].typename == "BDTOPO_V3:surface_hydrographique"
    assert PAR_ID["monuments_historiques"].typename == "wfs_sup:generateur_sup_s"
    assert not PAR_ID["cassini"].objets and fp.ECHELLE_MIN_OBJETS == 25000


def test_position_sur_la_frise():
    assert fp.position(PAR_ID["geologie"]) is None                          # sans date
    d, f = fp.position(PAR_ID["etat_major"])
    assert d == pytest.approx((1820 - 1750) / 280) and f == pytest.approx((1866 - 1750) / 280)
    d, f = fp.position(PAR_ID["photos"])                                    # jusqu'à aujourd'hui
    assert f == 1.0 and 0.9 < d < 1.0
    d, f = fp.position(PAR_ID["verdun_1916"])                               # une seule année
    assert d == f


def test_emprise_3857_bornee():
    x0, y0, x1, y1 = fp.emprise_3857(PAR_ID["cassini"])
    assert x0 < 0 < x1 and 5.0e6 < y0 < y1 < 6.8e6
    vx0, vy0, vx1, vy1 = fp.emprise_3857(PAR_ID["verdun_1916"])
    assert x0 < vx0 < vx1 < x1 and y0 < vy0 < vy1 < y1


def test_une_entree_incomplete_est_ignoree(tmp_path):
    p = tmp_path / "fonds.json"
    p.write_text('{"service": "s", "fonds": [{"id": "a"}, {"id": "b", "couche": "C", "titre": "T", '
                 '"epoque": "E", "format": "image/png", "style": "normal", "zmin": 0, "zmax": 5}]}', encoding="utf-8")
    service, fonds = fp.charger(p)
    assert service == "s" and [f.id for f in fonds] == ["b"]


def test_un_fond_indisponible_est_annonce():
    """2026-11-18 (dev/controle_flux.py) : un fond dont le service ne répond plus était écarté sans un mot,
    et l'utilisateur lisait « Aucun fond coché. » alors qu'il en avait coché un."""
    assert fp.resume_ajout(0, 0, indisponibles=1) == (
        "1 fond indisponible : son service ne répond pas ou ne le publie plus. Réessayez plus tard.")
    deux = fp.resume_ajout(3, 0, indisponibles=2)
    assert deux.startswith("3 fonds ajoutés") and deux.endswith(
        "2 fonds indisponibles : leur service ne répond pas ou ne les publie plus. Réessayez plus tard.")
    page = (RACINE / "src" / "ui" / "fonds_page.py").read_text(encoding="utf-8")
    assert "self.indisponibles.append(fond.titre)" in page
    assert "fp.resume_ajout(ajoutes, deja, indisponibles=len(self.indisponibles))" in page


def test_presence_filtree_sur_le_poste_jamais_par_le_service():
    """2026-11-18 : ``_presente`` envoyait le filtre au service ; sous QGIS 4 la Géoplateforme ne rend alors
    rien, et « Ajouter le contexte moderne » écartait les ronds-points à tort (18 dans la zone)."""
    page = (RACINE / "src" / "ui" / "fonds_page.py").read_text(encoding="utf-8")
    presente = page[page.index("def _presente("):page.index("def ajouter_fonds(")]
    code = presente.split('"""')[2]
    assert "setFilterExpression" not in code
    assert "QgsExpression(fond.filtre)" in code


def test_couche_sans_geometrie_passe_par_gdal():
    """2026-11-18 : quatre couches Géorisques s'ouvrent « valides » dans le fournisseur WFS de QGIS mais sans
    géométrie (jamais dessinées) ; le lecteur WFS de GDAL les dessine."""
    page = (RACINE / "src" / "ui" / "fonds_page.py").read_text(encoding="utf-8")
    assert "if (not couche.isValid() or not couche.isSpatial()) and fond.service_objets:" in page


def test_resume_de_l_ajout():
    assert "déjà" in fp.resume_ajout(0, 3)
    assert fp.resume_ajout(0, 0) == "Aucun fond coché."
    un = fp.resume_ajout(1, 0)
    assert un.startswith("1 fond ajouté dans QGIS, décoché :") and fp.GROUPE_FONDS in un
    assert fp.resume_ajout(12, 0).startswith("12 fonds ajoutés dans QGIS, décochés :")


# ----------------------------------------------------------------------
# Fiches des fonds et carte de couverture
# ----------------------------------------------------------------------
FICHES = fp.charger_fiches(RACINE / fp.FICHES)
COUVERTURES = fp.charger_couvertures(RACINE / fp.COUVERTURE)


def test_le_fichier_des_fiches_ne_nomme_que_des_fonds_du_catalogue():
    assert set(FICHES) == set(PAR_ID)


@pytest.mark.parametrize("fond", FONDS, ids=lambda f: f.id)
def test_chaque_fond_a_sa_fiche_complete_et_sourcee(fond):
    fiche = FICHES[fond.id]
    assert fiche.est_complete, fiche.manques
    assert len(fiche.usage) >= 2 and len(fiche.limites) >= 2 and fiche.origine
    for ref in fiche.references:
        assert ref.citation and ref.url.startswith(("https://", "http://")), ref     # un site savant sans https
    texte = " ".join((fiche.resume, fiche.lire) + fiche.usage + fiche.limites + fiche.origine)
    # Les marques de travail de la recherche documentaire ne partent pas dans le plugin.
    for marque in ("[source", "[sans source", "sans source", "TODO", "à vérifier"):
        assert marque not in texte, marque


@pytest.mark.parametrize("fond", FONDS, ids=lambda f: f.id)
def test_chaque_fond_a_son_apercu_et_son_lieu(fond):
    assert fond.lieu_apercu and (RACINE / fp.CATALOGUE.parent / fond.apercu).is_file()


def test_une_fiche_illisible_ou_absente_ne_casse_rien(tmp_path):
    assert fp.charger_fiches(tmp_path / "absent.json") == {}
    p = tmp_path / "fiches.json"
    p.write_text('{"_lisezmoi": ["x"], "cassini": {"resume": "R", "usage": "une seule"}}', encoding="utf-8")
    fiche = fp.charger_fiches(p)["cassini"]
    assert fiche.resume == "R" and fiche.usage == ("une seule",)
    assert not fiche.est_complete and "references" in fiche.manques
    assert fp.FicheFond().manques == fp.BLOCS_FICHE


def test_bornes_et_centre_d_une_case():
    ouest, sud, est, nord = fp.bornes_case(10, 518, 352)       # la case de Paris (10/518/352)
    assert ouest < 2.3522 < est and sud < 48.8566 < nord
    lon, lat = fp.centre_case(10, 518, 352)
    assert ouest < lon < est and sud < lat < nord


def test_la_couverture_est_mesuree_pour_chaque_fond():
    assert set(COUVERTURES) == set(PAR_ID)
    for c in COUVERTURES.values():
        assert c.zoom == 10 and 0.0 <= c.part <= 1.0 and len(set(c.cases)) == len(c.cases)


def test_la_couverture_dit_ce_que_l_on_sait_des_fonds():
    assert COUVERTURES["photos"].part > 0.99 and COUVERTURES["plan_ign"].part > 0.99
    for ident in ("batiments", "surfaces_en_eau", "routes_chemins", "parcelles", "zones_activite"):
        assert COUVERTURES[ident].part > 0.95, ident           # la BD TOPO et le cadastre couvrent le pays
    assert COUVERTURES["verdun_1916"].part < 0.02 and COUVERTURES["etat_major_10"].part < 0.05
    assert 0.02 < COUVERTURES["photos_1980"].part < 0.9            # incomplète, pas absente
    assert COUVERTURES["cassini"].part < 0.995                     # pas de Cassini en Corse
    # la case d'Ajaccio n'est pas dans Cassini, celle de Fénétrange y est
    def case(lon, lat):
        import math
        n = 2 ** 10
        return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    assert case(7.03, 48.86) in COUVERTURES["cassini"].cases
    assert case(9.0, 42.1) not in COUVERTURES["cassini"].cases


def test_phrase_de_couverture():
    assert fp.Couverture(10, (), 1.0).phrase == "Toute la France métropolitaine"
    assert fp.Couverture(10, (), 0.996).phrase == "Toute la France métropolitaine"
    assert fp.Couverture(10, (), 0.62).phrase == "Environ 62 % de la France métropolitaine"
    assert fp.Couverture(10, (), 0.004).phrase == "Moins de 1 % de la France métropolitaine"


def test_couverture_absente_ou_illisible(tmp_path):
    assert fp.charger_couvertures(tmp_path / "absent.json") == {}
    p = tmp_path / "c.json"
    p.write_text('{"zoom": 10, "x0": 5, "y0": 7, "cases_france": 4, "fonds": {"a": {"lignes": ["10", "01"]}}}',
                 encoding="utf-8")
    c = fp.charger_couvertures(p)["a"]
    assert c.cases == ((5, 7), (6, 8)) and c.part == 0.5


# ── 2026-11-12 : « Ajouter le contexte moderne », à la fin d'un traitement ────────────────────────────────────
def test_le_contexte_moderne_ajoute_les_donnees_que_cite_le_croisement():
    from src.app.services import contexte_croisement as cc

    couches = fp.couches_contexte(list(PAR_ID.values()))
    ids = [f.id for _g, f, _v in couches]
    assert len(ids) == len(set(ids)) and all(f.objets for _g, f, _v in couches)
    assert set(cc.ID_CATALOGUE.values()) <= set(ids)                                 # toutes celles de contexte_source
    cochees = {f.id for _g, f, v in couches if v}
    assert "routes_chemins" in ids and "routes_chemins" not in cochees               # les routes noient la carte
    # La sélection validée le 2026-11-12, sans les lieux-dits (2026-11-19 : retirés du croisement le 18/11,
    # de simples étiquettes de carte) : les autres présentes et décochées.
    assert cochees == {"ctx_ronds_points", "batiments", "ctx_reservoirs", "ctx_cimetieres", "surfaces_en_eau",
                       "cours_eau", "zones_habitation", "monuments_historiques",
                       "ctx_cavites", "ctx_mouvements_terrain",
                       # le patrimoine que croise le contexte (2026-11-19)
                       "archeo_plu_surfaces", "archeo_plu_points", "bretagne_zppa", "aura_zppa", "cvl_zppa"}
    assert len(ids) == 37                  # + talus de l'IGN et cinq données de patrimoine (2026-11-19)
    # Géorisques et les services régionaux (patrimoine) ont leur propre service ; le reste vient de la
    # Géoplateforme. Une couche « ms: » hors du catalogue est de Géorisques.
    for _g, fond, _v in couches:
        attendu = fond.service_objets or fp.SERVICE_OBJETS
        assert attendu in fp.uri_objets(fond), fond.id
        if fond.typename.startswith("ms:") and fond.id.startswith("ctx_"):
            assert fond.service_objets == fp.SERVICE_GEORISQUES


def test_le_contexte_moderne_est_range_par_famille_comme_dans_les_essais():
    couches = fp.couches_contexte(list(PAR_ID.values()))
    familles = list(dict.fromkeys(g for g, _f, _v in couches))
    assert familles == ["Routes et transports", "Bâti et constructions", "Hydrographie", "Relief recensé par l'IGN",
                        "Énergie et réseaux",
                        "Parcellaire et toponymie", "IGN complément", "Géorisques (BRGM)", "Patrimoine"]
    for _g, fond, _v in couches:
        assert fond.nom_couche == fond.titre                 # pas d'époque devant le nom
    par_id = {f.id: f for _g, f, _v in couches}
    assert par_id["batiments"].expression == PAR_ID["batiments"].expression          # la couche du catalogue, reprise
    assert par_id["monuments_historiques"].srs == "EPSG:4326"
    assert par_id["ctx_ronds_points"].filtre == '"nature" = \'Rond-point\''
    src = (RACINE / "src" / "ui" / "fonds_page.py").read_text(encoding="utf-8")
    assert "fp.GROUPE_CONTEXTE" in src and fp.GROUPE_CONTEXTE == "Contexte moderne"


def test_la_provenance_est_une_colonne_du_tableau():
    """Demande du 2026-11-12 : tout ne vient pas de l'IGN, la provenance se lit sans survoler."""
    assert all(f.source for f in PAR_ID.values())
    assert {"IGN", "BRGM"} <= {f.source for f in PAR_ID.values()}
    src = (RACINE / "src" / "ui" / "fonds_page.py").read_text(encoding="utf-8")
    assert 'QLabel("Provenance")' in src and 'setObjectName("FondProvenance")' in src
    assert src.count("setFixedWidth(W_PROVENANCE)") == 2          # la ligne et l'en-tête : colonnes alignées


def test_un_filtre_n_est_jamais_envoye_au_service():
    """La Géoplateforme répond « Internal Server Error » au filtre que QGIS écrit pour les servitudes
    (2026-11-12) : le filtre est une règle de dessin."""
    src = (RACINE / "src" / "ui" / "fonds_page.py").read_text(encoding="utf-8")
    assert "setSubsetString" not in src and "QgsRuleBasedRenderer.Rule(symbole, filterExp=fond.filtre)" in src


def test_le_contexte_moderne_n_ajoute_que_ce_qui_existe_dans_la_zone_etudiee():
    """Demande du 2026-11-12 : pas de couche vide dans l'arbre. La zone est l'emprise des mosaïques du
    traitement ; une donnée sans objet n'est pas ajoutée et le journal la nomme ; dans le doute, elle l'est."""
    page = (RACINE / "src" / "ui" / "fonds_page.py").read_text(encoding="utf-8")
    assert "def ajouter_contexte_moderne(self, zone=None, gpkg=None)" in page
    assert "def _presente(couche, fond: fp.Fond, zone)" in page
    assert "if zone is not None and fond.objets and not self._presente(couche, fond, zone):" in page
    assert "self.absentes.append(fond.titre)" in page
    presente = page[page.index("def _presente("):page.index("def ajouter_fonds(")]
    # Une limite envoyée au service faisait répondre « rien » à tort (53 cours d'eau, 0 trouvé).
    assert ".setLimit(" not in presente.split('"""')[2]
    assert presente.rstrip().endswith("return True")                # une erreur n'écarte jamais une donnée
    vue = (RACINE / "src" / "ui" / "run_view.py").read_text(encoding="utf-8")
    assert "page.ajouter_contexte_moderne(zone=self._zone_etudiee())" in vue
    assert 'glob("indices/*/tif/index_*.vrt")' in vue and "Sans objet dans la zone étudiée" in vue


def test_le_contexte_moderne_s_ajoute_meme_sans_modele_de_detection():
    """Demande du 2026-11-12 : le bouton est actif à la fin de tout traitement, pas seulement quand il y a
    un bilan de détections."""
    src = (RACINE / "src" / "ui" / "run_view.py").read_text(encoding="utf-8")
    assert "self._contexte_btn.setEnabled(self._iface is not None)" in src
    assert "self._contexte_btn.setEnabled(bool(self._bilan)" not in src


def test_le_bouton_est_a_cote_de_l_ajout_au_projet():
    src = (RACINE / "src" / "ui" / "run_view.py").read_text(encoding="utf-8")
    i = src.index("actions_fin.addWidget(self._open_project_btn)")
    assert src[i:].splitlines()[1].strip() == "actions_fin.addWidget(self._contexte_btn)"
    assert 'QPushButton("Ajouter le contexte moderne")' in src and "ajouter_contexte_moderne(zone=" in src


def test_le_contexte_moderne_se_lit_dans_le_dossier_du_traitement_quand_il_y_est():
    """Demande du 2026-11-13 : le clic prenait trop de temps (une question au service par donnée). Les six
    données du croisement sont lues dans ``livrable/contexte/contexte_moderne.gpkg`` ; sans ce fichier, le
    chemin en direct reste."""
    from src.app.services import contexte_gpkg as cg

    ids = {f.id for _g, f, _v in fp.couches_contexte(list(PAR_ID.values()))}
    assert set(cg.COUCHE_PAR_FOND) <= ids                        # chaque couche locale est une donnée du bouton
    page = (RACINE / "src" / "ui" / "fonds_page.py").read_text(encoding="utf-8")
    assert 'f"{gpkg}|layername={couche}"' in page and "if f.id in locales]" in page
    assert 'QgsVectorLayer(locale, fond.nom_couche, "ogr")' in page
    ajout = page[page.index("def ajouter_fonds("):page.index("def _couche_objets(")]
    assert ajout.index("if fond.id in locales:") < ajout.index("self._presente(couche, fond, zone)")   # aucune question
    vue = (RACINE / "src" / "ui" / "run_view.py").read_text(encoding="utf-8")
    assert "chemin_contexte(detections_dir(out_dir))" in vue and "page.ajouter_contexte_moderne(gpkg=local)" in vue


def test_un_bouton_decoche_tout_sans_toucher_au_projet():
    """Demande du 2026-11-13 : « Tout décocher », visible dès qu'une case est cochée, thèmes repliés compris."""
    src = (RACINE / "src" / "ui" / "fonds_page.py").read_text(encoding="utf-8")
    assert 'QPushButton("Tout décocher")' in src and "self._decocher.clicked.connect(self.tout_decocher)" in src
    corps = src[src.index("def tout_decocher("):src.index("def _sync_bouton(")]
    assert "for ligne in self._lignes.values():" in corps and "removeMapLayer" not in corps
    assert "self._decocher.setVisible(n > 0)" in src
