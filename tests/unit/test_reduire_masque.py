"""« Réduire » masque la fenêtre du plugin derrière une barrette flottante (2026-11-12) : réduite, une fenêtre
rattachée à QGIS devenait sous Windows une barre de titre minuscule en bas de l'écran. Contrôle par lecture du
source (src/ui n'est pas importable sans QGIS) ; le comportement est vérifié hors écran sous les deux QGIS
(recette § 77)."""
import ast
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "src" / "ui"
SOURCE = (UI / "wizard_dialog.py").read_text(encoding="utf-8")
CLASSE = next(n for n in ast.parse(SOURCE).body if isinstance(n, ast.ClassDef) and n.name == "WizardDialog")
METHODES = {n.name: ast.unparse(n) for n in CLASSE.body if isinstance(n, ast.FunctionDef)}
BARRETTE = (UI / "widgets" / "barrette.py").read_text(encoding="utf-8")


def test_la_reduction_est_interceptee():
    corps = METHODES["changeEvent"]
    assert "QEvent.Type.WindowStateChange" in corps and "isMinimized()" in corps
    assert "_masquer_au_lieu_de_reduire" in corps and "super().changeEvent(event)" in corps


def test_la_fenetre_est_masquee_sans_rester_reduite_ni_passer_par_la_fermeture():
    corps = METHODES["_masquer_au_lieu_de_reduire"] + METHODES["masquer_vers_barrette"]
    assert "~Qt.WindowState.WindowMinimized" in corps and "self.hide()" in corps and "montrer()" in corps
    for interdit in ("reject", "close", "resize", "setGeometry"):     # ni fermeture, ni changement de taille
        assert interdit not in corps, interdit


def test_la_barrette_rouvre_la_fenetre_et_s_efface_a_son_retour():
    assert "self.show()" in METHODES["rouvrir_depuis_barrette"]
    assert "_barrette.cacher()" in METHODES["showEvent"]
    assert "rouvrir = pyqtSignal()" in BARRETTE and "Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint" in BARRETTE


def test_la_barrette_dit_ou_on_en_est():
    corps = METHODES["_texte_barrette"]
    assert "is_running()" in corps and "RAIL_STEPS" in corps and "Catalogue des flux" in corps
