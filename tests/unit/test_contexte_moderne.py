"""Contexte moderne d'une détection : règles (qui exclut, qui informe) et phrases écrites."""
import pytest

from src.app.services import contexte_moderne as cm


def bati(distance=0.0, part=0.0, **attributs):
    return cm.Objet(cm.BATIMENT, attributs, distance, part)


def eau(distance=0.0, part=0.0, **attributs):
    return cm.Objet(cm.EAU, attributs, distance, part)


HANGAR = dict(nature="Industriel, agricole ou commercial", usage_1="Agricole", etat_de_l_objet="En service")
MAISON = dict(nature="Indifférenciée", usage_1="Résidentiel", etat_de_l_objet="En service")
MARE = dict(nature="Mare", origine="Naturelle non aménagée", persistance="Intermittent")
RETENUE = dict(nature="Retenue", origine="Artificielle", persistance="Permanent")


def test_les_cinq_champs_et_leur_ordre():
    assert cm.CHAMPS == ("contexte_moderne", "contexte_info", "contexte_dist_m", "contexte_part", "contexte_source")
    assert set(cm.champs([], source="s")) == set(cm.CHAMPS)


def test_un_batiment_exclut_s_il_recouvre_10_pourcent_de_la_detection():
    """Décision du 2026-11-13 : plus de rayon (5 m, 15 m pour les enclos), une part recouverte ; 5 % puis
    10 % le 2026-11-18 (galerie des cas : seule exclusion « probable », un enclos à 6 %, retombe)."""
    assert cm.PART_BATIMENT == 0.10
    for structure in ("", "enclos", "enclos_circulaires", "charbonnieres", "depressions_circulaires_grandes"):
        assert cm.effet(bati(0.0, 0.10, **HANGAR), structure) == cm.EXCLURE
        assert cm.effet(bati(0.0, 0.09, **HANGAR), structure) == cm.INFORMER      # il touche : dit, pas écarté
        assert cm.effet(bati(5.0, **MAISON), structure) == cm.INFORMER            # à côté : dit jusqu'à 5 m
        assert cm.effet(bati(5.4, **MAISON), structure) is None


@pytest.mark.parametrize("attributs", [
    dict(nature="Indifférenciée", etat_de_l_objet="En ruine"),
    dict(nature="Eglise", etat_de_l_objet="En service"),
    dict(nature="Chapelle"), dict(nature="Château"), dict(nature="Tour, donjon"), dict(nature="Moulin à vent"),
])
def test_une_ruine_ou_un_batiment_du_patrimoine_informe_sans_exclure(attributs):
    assert cm.effet(bati(2.0, **attributs)) == cm.INFORMER


def test_l_eau_amenagee_exclut_au_recouvrement_seulement():
    assert cm.effet(eau(0.0, 0.6, **RETENUE), "enclos") == cm.EXCLURE
    assert cm.effet(eau(0.0, 0.01, **RETENUE), "enclos") == cm.INFORMER     # à peine touchée (2026-11-18)
    assert cm.effet(eau(3.0, **RETENUE), "enclos") is None
    for nature in ("Réservoir-bassin", "Réservoir-bassin d'orage", "Plan d'eau de gravière", "Canal"):
        assert cm.effet(eau(0.0, 0.5, nature=nature, origine="Artificielle"), "fours") == cm.EXCLURE


def test_une_mare_informe_jusqu_a_quinze_metres_quelle_que_soit_la_structure():
    for structure in ("depressions_circulaires_grandes", "enclos", "talus_et_fosses"):
        assert cm.effet(eau(12.0, **MARE), structure) == cm.INFORMER
    assert cm.effet(eau(16.0, **MARE), "enclos") is None
    # même artificielle, une mare n'exclut pas : elle peut être une mardelle
    assert cm.effet(eau(0.0, nature="Mare", origine="Artificielle"), "enclos") == cm.INFORMER


def test_une_retenue_sous_un_talus_informe_la_digue_est_un_vrai_talus():
    for structure in ("talus_et_fosses", "talus_fosse", "Talus et fossés · talus", "fossé"):
        assert cm.est_talus(structure)
        assert cm.effet(eau(10.0, **RETENUE), structure) == cm.INFORMER
    assert not cm.est_talus("enclos") and not cm.est_talus("")
    assert cm.effet(eau(0.0, 0.5, nature="Retenue-digue", origine="Artificielle"), "enclos") == cm.EXCLURE


def test_l_eau_d_origine_naturelle_informe():
    assert cm.effet(eau(0.0, nature="Retenue", origine="Naturelle non aménagée"), "enclos") == cm.INFORMER
    assert cm.effet(eau(0.0, nature="Lac", origine="Artificielle"), "enclos") == cm.INFORMER      # nature non aménagée
    assert cm.effet(eau(0.0, nature="Ecoulement naturel"), "enclos") == cm.INFORMER
    assert cm.effet(eau(1.0, nature="Lac"), "enclos") is None


def test_une_source_inconnue_n_a_pas_d_effet():
    assert cm.effet(cm.Objet("route", {}, 0.0)) is None


@pytest.mark.parametrize("objet, attendu", [
    (bati(0.2, **HANGAR), "bâtiment agricole touchant la détection"),
    (bati(0.0, 0.25, **HANGAR), "bâtiment agricole recouvrant 25 % de la détection"),
    (bati(0.0, 0.004, **HANGAR), "bâtiment agricole touchant la détection"),       # moins de 1 %
    (bati(3.4, **MAISON), "bâtiment résidentiel à 3 m"),
    (bati(2.0, nature="Indifférenciée", usage_1="Indifférencié"), "bâtiment à 2 m"),
    (bati(1.0, nature="Indifférenciée", usage_1="Annexe", construction_legere=True), "annexe à 1 m (construction légère)"),
    (bati(4.6, nature="Eglise", usage_1="Religieux"), "église à 5 m"),
    (bati(0.0, nature="Tour, donjon"), "tour ou donjon touchant la détection"),
    (bati(2.0, nature="Indifférenciée", usage_1="Agricole", etat_de_l_objet="En ruine"), "bâtiment agricole en ruine à 2 m"),
    (bati(0.0, 1.0, nature="Serre", etat_de_l_objet="En construction"),
     "serre en construction recouvrant 100 % de la détection"),
    (eau(6.2, **MARE), "mare à 6 m (origine naturelle, eau intermittente)"),
    (eau(0.0, 0.8, **RETENUE), "étang (retenue) recouvrant 80 % de la détection"),
    (eau(6.2, **RETENUE), "étang (retenue) à 6 m"),
    (eau(0.0, 0.3, nature="Retenue-digue"), "plan d'eau endigué (retenue-digue) recouvrant 30 % de la détection"),
    (eau(0.0, 0.5, nature="Réservoir-bassin"), "bassin (réservoir-bassin) recouvrant 50 % de la détection"),
    (eau(2.0, nature="Ecoulement naturel"), "cours d'eau à 2 m"),
    (eau(0.0, nature="Retenue-barrage", cpx_toponyme_de_plan_d_eau="Étang du Stock"),
     "lac de barrage (retenue-barrage) « Étang du Stock » touchant la détection"),
    (eau(0.0, nature="Inconnue"), "surface en eau touchant la détection"),
    (eau(0.0), "surface en eau touchant la détection"),
])
def test_phrases(objet, attendu):
    assert cm.phrase(objet) == attendu


def test_champs_sans_objet_seule_la_source_est_remplie():
    c = cm.champs([], "enclos", "BD TOPO (IGN), lue le 2026-11-11", {cm.BATIMENT: "B"})
    assert c == {"contexte_moderne": None, "contexte_info": None, "contexte_dist_m": None, "contexte_part": None,
                 "contexte_source": "BD TOPO (IGN), lue le 2026-11-11"}


def test_champs_exclure_l_emporte_et_l_information_reste_lisible():
    c = cm.champs([eau(8.0, 0.0, **MARE), bati(0.0, 0.62, **HANGAR), bati(4.0, 0.0, **MAISON)], "enclos", "s")
    assert c["contexte_moderne"] == "bâtiment agricole recouvrant 62 % de la détection"   # le plus proche qui exclut
    assert c["contexte_info"] == "bâtiment résidentiel à 4 m ; mare à 8 m (origine naturelle, eau intermittente)"
    assert c["contexte_dist_m"] == 0 and c["contexte_part"] == 62              # ceux de l'objet qui décide


def test_champs_informer_seul_ne_remplit_pas_contexte_moderne():
    c = cm.champs([eau(6.0, 0.0, **MARE)], "depressions_circulaires_grandes", "s")
    assert c["contexte_moderne"] is None and c["contexte_info"].startswith("mare à 6 m")
    assert c["contexte_dist_m"] == 6 and c["contexte_part"] == 0


def test_champs_un_objet_hors_rayon_ne_compte_pas():
    c = cm.champs([bati(9.0, **HANGAR), eau(2.0, **RETENUE)], "charbonnieres", "s")
    assert c["contexte_moderne"] is None and c["contexte_info"] is None and c["contexte_dist_m"] is None


def test_champs_a_distance_egale_le_plus_recouvrant_gagne():
    c = cm.champs([bati(0.0, 0.1, **MAISON), bati(0.0, 0.8, **HANGAR)], "enclos", "s")
    assert c["contexte_moderne"].startswith("bâtiment agricole") and c["contexte_part"] == 80


def test_la_meme_retenue_exclut_un_enclos_et_informe_un_talus():
    objets = [eau(0.0, 0.4, **RETENUE)]
    assert cm.champs(objets, "enclos", "s")["contexte_moderne"] == "étang (retenue) recouvrant 40 % de la détection"
    talus = cm.champs(objets, "talus_et_fosses", "s")
    assert talus["contexte_moderne"] is None and talus["contexte_info"] == "étang (retenue) recouvrant 40 % de la détection"


def test_rayon_de_recherche_et_libelles():
    assert cm.RAYON_PROCHE == 15.0          # 25 m tant que les lieux-dits étaient croisés (avant le 2026-11-18)
    assert cm.RAYON_RECHERCHE == cm.RAYON_PATRIMOINE == 50.0      # le patrimoine se cherche plus loin (2026-11-19)
    assert cm.libelle_source("2026-11-11") == "BD TOPO (IGN), lue le 2026-11-11"
    assert cm.libelle_source("2026-11-12", ["Bâtiments"]) == "Bâtiments (BD TOPO, IGN), lue le 2026-11-12"
    assert cm.libelle_source("2026-11-12", ["Bâtiments", "Surfaces en eau et mares"]) == (
        "Bâtiments · Surfaces en eau et mares (BD TOPO, IGN), lue le 2026-11-12")


def test_la_source_est_celle_de_l_objet_qui_decide():
    titres = {cm.BATIMENT: "Bâtiments", cm.EAU: "Surfaces en eau et mares"}
    grise = cm.champs([eau(8.0, **MARE), bati(0.0, 0.5, **HANGAR)], "enclos", "tout", titres, "2026-11-12")
    # toutes les données citées, celle qui exclut d'abord
    assert grise["contexte_source"] == "Bâtiments · Surfaces en eau et mares (BD TOPO, IGN), lue le 2026-11-12"
    informe = cm.champs([eau(8.0, **MARE)], "enclos", "tout", titres, "2026-11-12")
    assert informe["contexte_source"] == "Surfaces en eau et mares (BD TOPO, IGN), lue le 2026-11-12"
    assert cm.champs([], "enclos", "tout", titres, "2026-11-12")["contexte_source"] == "tout"
    assert cm.resume(0, 0, 0) == ""
    assert cm.resume(0, 0, 12) == "Contexte moderne : rien à signaler autour de 12 détections."
    assert cm.resume(3, 5, 40) == ("Contexte moderne : sur 40 détections, 3 en contexte moderne "
                                   "(catégorie grise, décochée), 5 avec une information de contexte.")


def test_expression_de_la_legende():
    assert cm.expression_legende("fiabilite") == (
        "if(coalesce(\"contexte_moderne\", '') <> '', 'Contexte moderne', \"fiabilite\")")
    assert cm.expression_legende("conf_bin").endswith('"conf_bin")')
    deja = cm.expression_legende("fiabilite")
    assert cm.expression_legende(deja).count("Contexte moderne") == 2      # jamais appelé deux fois en pratique


def test_la_fabrique_des_couches_ajoute_la_categorie_sans_toucher_a_fiabilite():
    """La catégorie grise passe par une expression du rendu, décochée, et seulement si le champ existe."""
    from pathlib import Path

    racine = Path(__file__).resolve().parents[2]
    loader = (racine / "src/ui/layer_loader.py").read_text(encoding="utf-8")
    corps = loader.split("def _ajouter_contexte_moderne")[1].split("\ndef ")[0]
    assert 'indexFromName("contexte_moderne") < 0' in corps and "setRenderState(False)" in corps
    assert "setClassAttribute(expression_legende(" in corps and '"outline_style": "dash"' in corps
    # 2026-11-18 : en comparaison A/B, « Charbonnières — Structures linéaires… » n'est pas une structure linéaire
    assert "est_lineaire(layer.name().split(\" — \")[0])" in corps
    fabrique = loader.split("def build_detection_vector_layer")[1].split("\ndef ")[0]
    assert "_ajouter_contexte_moderne(layer, logger)" in fabrique
    # les quatre niveaux de fiabilité ne bougent pas
    from src.app.services import fiabilite
    assert cm.CATEGORIE_LEGENDE not in fiabilite.LABELS_FR.values() and len(fiabilite.CATEGORIES) == 4


def test_case_de_l_etape_4_cochee_par_defaut_et_persistee():
    from pathlib import Path
    import json

    racine = Path(__file__).resolve().parents[2]
    from config.config_manager import ConfigManager
    assert ConfigManager(racine).default_config()["computer_vision"]["contexte_moderne"] is True
    assert json.loads((racine / "config.example.json").read_text(encoding="utf-8"))["computer_vision"]["contexte_moderne"] is True
    etape4 = (racine / "src/ui/steps/step_4_launch.py").read_text(encoding="utf-8")
    assert "self._contexte_check.setChecked(True)" in etape4 and "contexte_moderne_changed" in etape4
    wizard = (racine / "src/ui/wizard_dialog.py").read_text(encoding="utf-8")
    assert 'set_contexte_moderne(bool(cv.get("contexte_moderne", True)))' in wizard
    assert '["contexte_moderne"] = bool(on)' in wizard


# ── 2026-11-12 : cours d'eau, zones d'habitation, ronds-points, lieux-dits (structures ponctuelles) ──────────
def autre(source, distance=0.0, part=0.0, **attributs):
    return cm.Objet(source, attributs, distance, part)


RUISSEAU = dict(nature="Ecoulement naturel", origine="Naturelle non aménagée", persistance="Intermittent")
HAMEAU = dict(nature="Lieu-dit habité", toponyme="Hameau du Ruisseau des Écrevisses")


def test_un_cours_d_eau_informe_qu_il_traverse_ou_qu_il_longe():
    c = cm.champs([autre(cm.COURS_EAU, 0.0, **RUISSEAU)], "enclos", "s")
    assert c["contexte_moderne"] is None and c["contexte_info"] == "cours d'eau traversant la détection (intermittent)"
    semouse = dict(nature="Ecoulement naturel", persistance="Permanent", cpx_toponyme_de_cours_d_eau="la Semouse")
    assert cm.champs([autre(cm.COURS_EAU, 4.4, **semouse)], "enclos_circulaires", "s")["contexte_info"] == (
        "cours d'eau « la Semouse » à 4 m")
    assert cm.champs([autre(cm.COURS_EAU, 16.0, **RUISSEAU)], "enclos", "s")["contexte_info"] is None
    # l'axe d'un étang est déjà dit par la surface en eau
    assert cm.champs([autre(cm.COURS_EAU, 0.0, nature="Retenue")], "enclos", "s")["contexte_info"] is None


def test_une_zone_d_habitation_informe_sans_jamais_exclure():
    """Décision du 2026-11-13 : la zone d'habitation ne grise plus, même quand la détection est dedans."""
    dedans = cm.champs([autre(cm.HABITATION, 0.0, 0.8, **HAMEAU)], "enclos", "s")
    assert dedans["contexte_moderne"] is None
    assert dedans["contexte_info"] == "dans la zone d'habitation « Hameau du Ruisseau des Écrevisses »"
    assert dedans["contexte_part"] == 80
    bord = cm.champs([autre(cm.HABITATION, 0.0, 0.2, **HAMEAU)], "enclos", "s")
    assert bord["contexte_moderne"] is None
    assert bord["contexte_info"] == "zone d'habitation « Hameau du Ruisseau des Écrevisses » recouvrant 20 % de la détection"
    assert cm.champs([autre(cm.HABITATION, 3.0, 0.0, **HAMEAU)], "enclos", "s")["contexte_info"] is None


@pytest.mark.parametrize("nature, mot", [("Ruines", "ruines"), ("Château", "château"), ("Moulin", "moulin")])
def test_ruines_chateau_et_moulin_informent_sans_exclure(nature, mot):
    c = cm.champs([autre(cm.HABITATION, 0.0, 0.9, nature=nature, toponyme="le Vieux")], "fours", "s")
    assert c["contexte_moderne"] is None
    assert c["contexte_info"] == f"{mot} « le Vieux » recouvrant 90 % de la détection"


def test_un_rond_point_exclut_la_detection_posee_dessus():
    dessus = cm.champs([autre(cm.ROND_POINT, 0.0, 0.97)], "enclos_circulaires", "s")
    assert dessus["contexte_moderne"] == "rond-point recouvrant 97 % de la détection"


def test_un_rond_point_exclut_a_partir_de_10_pour_cent():
    """2026-11-19 : même part que le bâti et l'eau. Un enclos de 25 m de rayon autour d'un rond-point de 15 m
    n'est recouvert qu'à 36 % : à 50 %, il n'était qu'informé alors que c'est le rond-point lui-même."""
    autour = cm.champs([autre(cm.ROND_POINT, 0.0, 0.36)], "enclos", "s")
    assert autour["contexte_moderne"] == "rond-point recouvrant 36 % de la détection"
    assert cm.champs([autre(cm.ROND_POINT, 0.0, 0.10)], "enclos", "s")["contexte_moderne"] is not None
    bord = cm.champs([autre(cm.ROND_POINT, 0.0, 0.09)], "enclos", "s")
    assert bord["contexte_moderne"] is None and bord["contexte_info"] == "rond-point recouvrant 9 % de la détection"


def test_les_lieux_dits_ne_sont_plus_croises():
    """Décision du 2026-11-18 : un lieu-dit est une étiquette de carte ; il gonflait le compteur « avec une
    information » (« Forêt Domaniale de Vimy » sur 42 cratères) sans rien apprendre."""
    assert not hasattr(cm, "LIEU_DIT") and "lieu_dit" not in cm.SOURCES_PONCTUELLES
    assert cm.RAYON_PROCHE == 15.0          # le plus grand rayon restant hors patrimoine : mares, digues, cours d'eau


def test_l_eau_amenagee_suit_la_meme_part_minimale_que_le_bati():
    """Décision du 2026-11-18 : un plan d'eau aménagé écartait au moindre contact (4 exclusions sur 14 à
    Fénétrange touchaient l'eau sur 1 à 4 %) ; il suit désormais la part minimale du bâti."""
    gr = dict(nature="Plan d'eau de gravière", origine="Artificielle")
    a_peine = cm.champs([cm.Objet(cm.EAU, gr, 0.0, 0.09)], "enclos", "s")
    assert a_peine["contexte_moderne"] is None
    assert a_peine["contexte_info"] == "plan d'eau de gravière recouvrant 9 % de la détection"
    assert cm.champs([cm.Objet(cm.EAU, gr, 0.0, 0.10)], "charbonnieres", "s")["contexte_moderne"] == (
        "plan d'eau de gravière recouvrant 10 % de la détection")
    assert cm.PART_EXCLUSION == 0.10                   # seuil retenu par l'utilisateur le 2026-11-18


def test_les_batiments_se_cumulent():
    """2026-11-18 : la part était mesurée bâtiment par bâtiment ; deux bâtiments à 6 % ne grisaient pas une
    détection qu'ils recouvrent à 12 %."""
    c = cm.champs([bati(0.0, 0.06, **HANGAR), bati(0.0, 0.06, **MAISON)], "enclos", "s")
    assert c["contexte_moderne"] == "2 bâtiments recouvrant 12 % de la détection" and c["contexte_part"] == 12
    assert cm.champs([bati(0.0, 0.06, **HANGAR)], "enclos", "s")["contexte_moderne"] is None
    eglise = dict(nature="Eglise")                     # le patrimoine ne s'additionne pas au bâti moderne
    assert cm.champs([bati(0.0, 0.06, **HANGAR), bati(0.0, 0.06, **eglise)], "enclos", "s")["contexte_moderne"] is None


@pytest.mark.parametrize("structure", ["talus_et_fosses Talus", "chemins_creux", "parcellaire", "tranchees_et_boyaux"])
def test_les_structures_lineaires_ne_recoivent_pas_les_nouvelles_donnees(structure):
    objets = [autre(cm.COURS_EAU, 0.0, **RUISSEAU), autre(cm.HABITATION, 0.0, 0.9, **HAMEAU),
              autre(cm.ROND_POINT, 0.0, 0.9)]
    c = cm.champs(objets, structure, "s")
    assert c["contexte_moderne"] is None and c["contexte_info"] is None and c["contexte_source"] == "s"
    assert cm.est_lineaire(structure)


@pytest.mark.parametrize("structure", ["charbonnieres", "fours", "depressions_circulaires_grandes", "enclos",
                                       "enclos_circulaires", "crateres"])
def test_les_structures_ponctuelles(structure):
    assert not cm.est_lineaire(structure)


def test_plusieurs_motifs_un_par_donnee_le_plus_proche_d_abord():
    titres = {cm.BATIMENT: "Bâtiments", cm.HABITATION: "Zones d'habitation", cm.COURS_EAU: "Cours d'eau"}
    c = cm.champs([bati(3.0, 0.0, **MAISON), bati(0.0, 0.2, **HANGAR), autre(cm.HABITATION, 0.0, 0.7, **HAMEAU),
                   autre(cm.COURS_EAU, 6.0, **RUISSEAU)],
                  "enclos", "s", titres, "2026-11-12")
    # un motif par donnée et par effet : le bâtiment qui exclut, puis ce qui informe, le plus proche d'abord
    assert c["contexte_moderne"] == "bâtiment agricole recouvrant 20 % de la détection"
    assert c["contexte_info"] == ("dans la zone d'habitation « Hameau du Ruisseau des Écrevisses » ; "
                                  "bâtiment résidentiel à 3 m ; cours d'eau à 6 m (intermittent)")
    assert (c["contexte_dist_m"], c["contexte_part"]) == (0, 20)                 # le premier motif qui exclut
    assert c["contexte_source"] == ("Bâtiments · Zones d'habitation · Cours d'eau (BD TOPO, IGN), "
                                    "lue le 2026-11-12")


# ── revue de Fénétrange, 2026-11-12 : la règle dépend de la structure ─────────────────────────────────────
def test_un_batiment_a_14_m_d_un_enclos_ne_l_ecarte_plus():
    """986958, 6863673 : le rayon de 15 m des enclos a disparu le 2026-11-13 (part recouverte seulement)."""
    for structure in ("enclos Enclos", "enclos_circulaires", "charbonnieres"):
        c = cm.champs([bati(13.7, **HANGAR)], structure, "s")
        assert c["contexte_moderne"] is None and c["contexte_info"] is None
    assert not hasattr(cm, "RAYON_BATIMENT_ENCLOS")


def test_un_batiment_n_ecarte_une_depression_que_s_il_est_dessus():
    """986553, 6859838 : à côté, il informe ; dessus, il écarte."""
    a_cote = cm.champs([bati(0.7, **MAISON)], "depressions_circulaires_grandes", "s")
    assert a_cote["contexte_moderne"] is None and a_cote["contexte_info"] == "bâtiment résidentiel à 1 m"
    dessus = cm.champs([bati(0.0, 0.3, **MAISON)], "depressions_circulaires_grandes", "s")
    assert dessus["contexte_moderne"] == "bâtiment résidentiel recouvrant 30 % de la détection"
    assert cm.champs([bati(6.0, **MAISON)], "depressions_circulaires_grandes", "s")["contexte_info"] is None


def test_un_etang_informe_une_depression_sans_l_ecarter():
    """988053, 6871483 : la cuvette peut avoir précédé l'étang."""
    c = cm.champs([eau(0.0, 0.7, **RETENUE)], "depressions_circulaires_grandes", "s")
    assert c["contexte_moderne"] is None and c["contexte_info"] == "étang (retenue) recouvrant 70 % de la détection"
    assert cm.champs([eau(0.0, 0.7, **RETENUE)], "enclos", "s")["contexte_moderne"] is not None      # ailleurs, il écarte


@pytest.mark.parametrize("structure", ["talus_et_fosses Talus", "chemins_creux", "parcellaire", "tranchees_et_boyaux"])
def test_une_structure_lineaire_n_est_jamais_ecartee(structure):
    c = cm.champs([bati(0.0, 0.4, **HANGAR), eau(0.0, 0.2, nature="Canal", origine="Artificielle")], structure, "s")
    assert c["contexte_moderne"] is None
    assert c["contexte_info"] == "bâtiment agricole recouvrant 40 % de la détection ; canal recouvrant 20 % de la détection"
    assert cm.effet(bati(0.0, **HANGAR), structure) == cm.INFORMER


# ── 2026-11-12 : la ligne d'état du contexte moderne, sous le bilan de fin de traitement ───────────────────
def test_ligne_etat_dit_ce_que_le_croisement_a_fait():
    trace = {"total": 952, "marquees": 67, "informees": 148, "motif": "",
             "source": "Bâtiments · Cours d'eau (BD TOPO, IGN), lue le 2026-11-12"}
    assert cm.ligne_etat(trace) == ("Contexte moderne : 67 détections grisées, 148 avec une information · "
                                    "données de l'IGN lues le 12/11/2026")
    assert cm.ligne_etat({"total": 9, "marquees": 1, "informees": 0}) == "Contexte moderne : 1 détection grisée"
    assert cm.ligne_etat({"total": 9, "marquees": 0, "informees": 0, "source": "x, lue le 2026-01-05"}) == (
        "Contexte moderne : rien à signaler · données de l'IGN lues le 05/01/2026")


def test_ligne_etat_dit_pourquoi_le_croisement_n_est_pas_fait():
    motif = "Contexte moderne non vérifié : la BD TOPO de l'IGN est injoignable (OSError)."
    assert cm.ligne_etat({"total": 0, "motif": motif}) == motif
    assert cm.ligne_etat(None) == "" and cm.ligne_etat({}) == "" and cm.ligne_etat({"total": 0}) == ""


def test_les_linéaires_longent_mais_ne_sont_jamais_ecartes():
    for source, attributs, attendu in (
            (cm.ROUTE, {"nature": "Chemin"}, "longe un chemin sur 80 % de sa longueur"),
            (cm.VOIE_FERREE, {"nature": "Voie ferrée principale"}, "longe une voie ferrée sur 80 % de sa longueur"),
            (cm.TALUS_IGN, {"nature": "Talus"}, "longe un talus recensé par l'IGN sur 80 % de sa longueur"),
            (cm.CANALISATION, {"nature": "Eau"}, "longe une canalisation sur 80 % de sa longueur"),
            (cm.COURS_EAU, {"nature": "Ecoulement naturel"}, "longe un cours d'eau sur 80 % de sa longueur")):
        c = cm.champs([cm.Objet(source, attributs, 0.0, 0.8)], "talus_et_fosses", "s")
        assert c["contexte_info"] == attendu and c["contexte_moderne"] is None, source
    # sous le seuil, une ligne qui croise ou effleure ne dit rien
    assert cm.champs([cm.Objet(cm.ROUTE, {}, 0.0, cm.PART_LONGE - 0.01)], "parcellaire", "s")["contexte_info"] is None


def test_qui_consulte_quoi():
    assert cm.consulte(cm.ROUTE, "chemins_creux") and not cm.consulte(cm.ROUTE, "charbonnieres")
    assert cm.consulte(cm.COURS_EAU, "chemins_creux") and cm.consulte(cm.COURS_EAU, "charbonnieres")
    assert not cm.consulte(cm.ROND_POINT, "parcellaire") and cm.consulte(cm.BATIMENT, "parcellaire")


# ── 2026-11-19 : le patrimoine connu informe « site connu à proximité », jamais n'écarte ───────────────────
def test_le_patrimoine_informe_sans_jamais_ecarter():
    zone = cm.Objet(cm.ZPPA_BRETAGNE, {"COMMUNE": "Rennes", "N_ZONE": "12"}, 0.0, 1.0)
    for structure in ("enclos", "talus_et_fosses", "charbonnieres"):
        c = cm.champs([zone], structure, "s")
        assert c["contexte_moderne"] is None
        assert c["contexte_info"] == ("site connu : dans la zone de présomption de prescription archéologique "
                                      "(Rennes, zone 12)")
    mh = cm.Objet(cm.MONUMENT, {"nomsuplitt": "Château de Fénétrange"}, 32.4)
    assert cm.champs([mh], "enclos", "s")["contexte_info"] == \
        "site connu à proximité : monument historique « Château de Fénétrange » à 32 m"
    assert cm.champs([cm.Objet(cm.MONUMENT, {}, cm.RAYON_PATRIMOINE + 1)], "enclos", "s")["contexte_info"] is None


def test_la_source_d_une_information_de_patrimoine_n_est_pas_la_bd_topo():
    c = cm.champs([cm.Objet(cm.PLU_POINT, {"libelle": "Site gallo-romain"}, 10.0)], "enclos", "",
                  {cm.PLU_POINT: "Archéologie des PLU (points)"}, "2026-11-19")
    assert c["contexte_source"] == "Archéologie des PLU (points) (données publiques), lue le 2026-11-19"
    assert cm.base_de([cm.BATIMENT, cm.EAU]) == "BD TOPO, IGN"


# ── 2026-11-19 : exclusions à calibrer (réservoirs, épuration, terrains de sport, parkings) ──────────────────
def test_les_exclusions_a_calibrer_n_ecartent_pas_tant_qu_elles_ne_sont_pas_activees(monkeypatch):
    parking = cm.Objet(cm.PARKING, {"nature": "Parking"}, 0.0, 0.4)
    assert cm.EXCLUSIONS_ACTIVES == frozenset()            # en attente du jugement de l'utilisateur
    c = cm.champs([parking], "enclos", "s")
    assert c["contexte_moderne"] is None and c["contexte_info"] == "parking recouvrant 40 % de la détection"
    monkeypatch.setattr(cm, "EXCLUSIONS_ACTIVES", frozenset({cm.PARKING}))
    assert cm.champs([parking], "enclos", "s")["contexte_moderne"] == "parking recouvrant 40 % de la détection"
    sous = cm.champs([cm.Objet(cm.PARKING, {}, 0.0, 0.05)], "enclos", "s")
    assert sous["contexte_moderne"] is None and sous["contexte_info"] == "parking recouvrant 5 % de la détection"
    assert cm.champs([parking], "parcellaire", "s")["contexte_info"] is None      # jamais les linéaires


def test_noms_des_objets_a_calibrer():
    for source, nature, nom in ((cm.RESERVOIR, "Réservoir d'eau ou château d'eau au sol", "réservoir d'eau au sol"),
                                (cm.EPURATION, "Station d'épuration", "station d'épuration"),
                                (cm.EPURATION, "Déchèterie", "déchèterie"),
                                (cm.TERRAIN_SPORT, "Grand terrain de sport", "grand terrain de sport")):
        assert cm.phrase(cm.Objet(source, {"nature": nature}, 0.0, 0.3)) == f"{nom} recouvrant 30 % de la détection"
