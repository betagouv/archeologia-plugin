"""Décharger l'extension ne laisse ni fenêtre ni barrette orpheline (recette 77, 2026-11-19).

Après un rechargement de l'extension, la barrette de l'ancienne fenêtre restait collée à la fenêtre de QGIS
(« Étape 5 · Traitement »), son horloge appelant l'ancien code, à côté de celle de la nouvelle fenêtre.
``main.py`` et ``src/ui`` ne s'importent pas hors de QGIS : on lit leur source.
"""
import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]


def _fonction(chemin: Path, nom: str) -> str:
    source = chemin.read_text(encoding="utf-8")
    for noeud in ast.walk(ast.parse(source)):
        if isinstance(noeud, ast.FunctionDef) and noeud.name == nom:
            return ast.get_source_segment(source, noeud)
    raise AssertionError(f"{nom} introuvable dans {chemin.name}")


def test_unload_libere_la_fenetre():
    assert "liberer()" in _fonction(RACINE / "main.py", "unload")


def test_liberer_supprime_la_barrette_et_cache_la_fenetre():
    corps = _fonction(RACINE / "src" / "ui" / "wizard_dialog.py", "liberer")
    assert "cacher()" in corps and "deleteLater()" in corps and "self.hide()" in corps
