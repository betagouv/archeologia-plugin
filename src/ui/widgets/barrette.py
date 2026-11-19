"""Barrette flottante : ce qui reste de l'assistant quand sa fenêtre est masquée.

Décision de l'utilisateur (2026-11-12). Réduite, une fenêtre rattachée à QGIS devenait sous Windows une
barre de titre minuscule en bas de l'écran ; resserrée pendant le choix des dalles sur la carte, elle
changeait de taille. Dans les deux cas la fenêtre est maintenant **masquée telle quelle** et cette
barrette prend sa place : une ligne qui dit où on en est (« Étape 3 · Structures à chercher »,
« Traitement en cours · 12min 03s »), posée en haut à droite de la fenêtre de QGIS, au-dessus de la
carte. Un clic la referme et rouvre l'assistant ; l'icône du plugin fait de même.

Fenêtre-outil sans cadre, enfant de la fenêtre de QGIS : elle reste au-dessus de QGIS sans passer
au-dessus des autres applications, et n'a pas d'entrée dans la barre des tâches.
"""
from __future__ import annotations

from typing import Callable, Optional

from qgis.PyQt.QtCore import Qt, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

MARGE = 12          # écart au coin haut droit de la fenêtre de QGIS
SOUS_LES_BARRES = 96  # sous le titre, les menus et les barres d'outils


class Barrette(QFrame):
    """Une ligne d'état et un bouton ; ``rouvrir`` est émis au clic, où qu'il tombe."""

    rouvrir = pyqtSignal()

    def __init__(self, parent=None, texte: Optional[Callable[[], str]] = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("Barrette")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Rouvrir Archéolog'IA")
        # Enfant de la fenêtre de QGIS, pas de l'assistant : le thème de l'assistant ne l'atteint pas.
        self.setStyleSheet(
            "#Barrette { background: #ffffff; border: 1px solid #1d5a96; border-radius: 4px; }"
            "#BarretteNom { color: #1d5a96; font-weight: bold; font-size: 11px; }"
            "#BarretteEtat { color: #2b2f33; font-size: 11px; }"
            "#BarretteBouton { font-size: 11px; font-weight: bold; color: #ffffff; background: #1d5a96;"
            " border: 1px solid #1d5a96; border-radius: 2px; padding: 3px 12px; }"
            "#BarretteBouton:hover { background: #2b79c2; }")
        self._texte = texte or (lambda: "")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 6, 6)
        lay.setSpacing(10)
        nom = QLabel("Archéolog'IA")
        nom.setObjectName("BarretteNom")
        lay.addWidget(nom)
        self._etat = QLabel("")
        self._etat.setObjectName("BarretteEtat")
        lay.addWidget(self._etat, 1)
        self._bouton = QPushButton("Rouvrir")
        self._bouton.setObjectName("BarretteBouton")
        self._bouton.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bouton.clicked.connect(self.rouvrir.emit)
        lay.addWidget(self._bouton)
        # L'état vit (chrono du traitement) : relu chaque seconde tant que la barrette est montrée.
        self._horloge = QTimer(self)
        self._horloge.setInterval(1000)
        self._horloge.timeout.connect(self.rafraichir)

    def etat(self) -> str:
        return self._etat.text()

    def rafraichir(self) -> None:
        texte = self._texte()
        if texte != self._etat.text():
            self._etat.setText(texte)
            self.adjustSize()
            self._placer()

    def montrer(self) -> None:
        self.rafraichir()
        self.adjustSize()
        self._placer()
        self.show()
        self._horloge.start()

    def cacher(self) -> None:
        self._horloge.stop()
        self.hide()

    def _placer(self) -> None:
        """En haut à droite de la fenêtre de QGIS (sinon de l'écran), sous ses barres d'outils."""
        hote = self.parentWidget()
        try:
            cadre = hote.frameGeometry() if hote is not None else self.screen().availableGeometry()
        except Exception:  # noqa: BLE001 — pas d'écran (tests hors session graphique)
            return
        self.move(cadre.right() - self.width() - MARGE, cadre.top() + SOUS_LES_BARRES)

    def mouseReleaseEvent(self, event):  # noqa: N802 (signature Qt)
        if event.button() == Qt.MouseButton.LeftButton:
            self.rouvrir.emit()
        super().mouseReleaseEvent(event)
