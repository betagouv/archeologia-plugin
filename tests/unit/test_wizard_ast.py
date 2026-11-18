"""Contrats de l'assistant vérifiés par AST (``src/ui`` n'est pas importable hors
QGIS) : un seul menu « Configuration ▾ », messages sous les champs de l'étape 1."""
import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
WIZARD = RACINE / "src" / "ui" / "wizard_dialog.py"
STEP1 = RACINE / "src" / "ui" / "steps" / "step_1_source.py"


def _chaines(source: str) -> list:
    return [n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_un_seul_bouton_configuration():
    chaines = _chaines(WIZARD.read_text(encoding="utf-8"))
    assert chaines.count("Configuration") == 1   # le bouton-menu ; Qt dessine la flèche
    for ancien in ("Charger une configuration", "Enregistrer la configuration", "Charger une config", "Enregistrer la config"):
        assert ancien not in chaines, ancien


def test_le_menu_porte_toutes_les_entrees():
    chaines = _chaines(WIZARD.read_text(encoding="utf-8"))
    for entree in ("Enregistrer sous…", "Gérer les configurations…", "Importer un fichier…",
                   "Tout remettre aux valeurs par défaut…", "Aucune configuration enregistrée"):
        assert entree in chaines, entree


def test_reinitialisation_globale_dans_le_menu_seulement():
    src = WIZARD.read_text(encoding="utf-8")
    assert src.count("_reset_to_defaults") == 2, "une définition et un seul branchement, depuis le menu"


def test_messages_sous_les_champs_de_l_etape_1():
    src = STEP1.read_text(encoding="utf-8")
    assert "message_champ(" in src
    assert src.count('setObjectName("FieldMessage")') == 3, \
        "un message sous la source, un sous le dossier de sortie, un sous le nom de l'analyse"


# ---------------------------------------------------------------- lot 9 (2026-10-24)
RUN_VIEW = RACINE / "src" / "ui" / "run_view.py"
PAGE6 = RACINE / "src" / "ui" / "steps" / "step_6_resultats.py"


def test_six_etapes_dans_le_rail():
    src = WIZARD.read_text(encoding="utf-8")
    assert src.count('{"label": ') == 6 and '{"label": "Résultats"' in src
    assert "STEP_RESULTATS = 6" in src and "ResultatsPage(" in src
    # « Revoir les résultats » retiré de la vue du traitement (2026-11-12) : l'étape 6 se rejoint par le rail.
    assert "revoir_resultats" not in src and "Revoir les résultats" not in RUN_VIEW.read_text(encoding="utf-8")
    assert "class ResultatsPage" in PAGE6.read_text(encoding="utf-8")
    from src.app.services.aide import CHAPITRE_PAR_ETAPE
    assert CHAPITRE_PAR_ETAPE[6] == "resultats"


def test_relancer_passe_par_apply_config():
    src = WIZARD.read_text(encoding="utf-8")
    corps = src[src.index("def _relancer_depuis_resultat("):src.index("def _on_mode_changed(")]
    assert "self._apply_config(" in corps and "self._goto_step(3)" in corps


def test_selection_sur_carte_sans_minimiser():
    """Choisir les dalles sur la carte ne réduit pas l'assistant et ne change plus sa taille
    (2026-11-12) : il est masqué derrière la barrette, puis remontré tel quel."""
    src = STEP1.read_text(encoding="utf-8")
    assert "showMinimized(" not in src and "setGeometry(" not in src and "_geometrie_avant_carte" not in src
    assert 'masquer_vers_barrette("Choix des dalles sur la carte")' in src and "win.show()" in src


def test_l_etape_4_recoit_les_avertissements_de_configuration():
    """Les avertissements de validate_run_context vont au bandeau de l'étape 4 (crash test it_piemonte, 2026-11-02)."""
    src = WIZARD.read_text(encoding="utf-8")
    assert "errors, _warnings = validate_run_context" not in src
    assert "self._launch_page.set_validation(errors, self._validation_warnings)" in src
