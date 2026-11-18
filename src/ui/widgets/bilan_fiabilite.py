"""Bilan de fiabilité de fin de run — un tableau, une rangée par structure.

Refonte du 2026-11-12 (validée par l'utilisateur) : les barres doublées d'une phrase laissent la place à
un tableau. Par rangée : la pastille de couleur et le libellé de la structure, une barre **en parts**
(elle occupe toute sa largeur, quelle que soit la taille de la structure : 18 charbonnières se lisent
aussi bien que 728 cratères ; le volume se lit dans la colonne « total »), puis une colonne de chiffres
par niveau, du plus sûr au plus douteux, la colonne grise des détections en **contexte moderne** et le
total. L'en-tête sert de légende. Les segments sont dans la couleur de la couche déclinée par niveau —
exactement les teintes de la légende de QGIS (``profil_scores.teinte_niveau``) — et le gris est celui de
la catégorie « Contexte moderne ». Survoler une rangée donne la phrase du bilan. Données : module pur
:mod:`app.services.bilan_fiabilite`. Compatible Qt5/Qt6 : énumérés scopés.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from qgis.PyQt.QtCore import QEvent, QRectF, QSize, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from qgis.PyQt.QtWidgets import QSizePolicy, QToolTip, QWidget

from ...app.services.bilan_fiabilite import LIBELLE_ECARTEES, LigneBilan
from .profil_scores import RGB, couleur_de_classe, teinte_niveau

_ENTETE = 20             # la rangée des titres de colonne
_RANGEE = 24
_BARRE_H = 12
_LARGEUR_LIBELLE = 190
_BARRE_MIN = 90
_MARGE_COL = 16          # air à gauche de chaque colonne de chiffres
_PASTILLE = 9
_BLEU_DEFAUT: RGB = (42, 120, 214)
_ENCRE = QColor("#2c2c2c")
_ENCRE_DOUCE = QColor("#4f5a66")         # le gris de texte atténué du thème (7:1 sur blanc)
_ENCRE_VIDE = QColor("#b8bcc1")          # le tiret d'une case vide : un repère, pas une valeur
_FILET = QColor("#e6e8eb")
_FOND_BARRE = QColor("#efefef")
_GRIS_ECARTEES = QColor("#8a8f94")       # la couleur de la catégorie « Contexte moderne » de la légende
_TOTAL = "total"


def _nb(n: int) -> str:
    return f"{n:,}".replace(",", " ")


class BilanFiabiliteWidget(QWidget):
    """Le tableau du bilan ; hauteur fixée par le nombre de rangées."""

    def __init__(self, lignes: Sequence[LigneBilan], parent=None):
        super().__init__(parent)
        self._lignes: List[LigneBilan] = list(lignes)
        self._bases: List[RGB] = [couleur_de_classe(ligne.couche) or _BLEU_DEFAUT for ligne in self._lignes]
        self._niveaux: List[Tuple[str, str]] = [(c, lab.lower()) for c, lab in legende_niveaux(self._lignes)]
        self._contexte = any(ligne.n_ecartees > 0 for ligne in self._lignes)
        self.setObjectName("BilanFiabilite")
        h = _ENTETE + len(self._lignes) * _RANGEE + 4
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)
        self.setMinimumWidth(_LARGEUR_LIBELLE + _BARRE_MIN + sum(w for _t, w in self._colonnes()))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip("\n".join(ligne.phrase() for ligne in self._lignes))

    # ------------------------------------------------------------------ colonnes
    def _polices(self) -> Tuple[QFont, QFont, QFont]:
        """(titres de colonne, chiffres, total en gras)."""
        titre = QFont(self.font())
        titre.setPointSizeF(max(7.0, self.font().pointSizeF() - 1))
        gras = QFont(self.font())
        gras.setBold(True)
        return titre, QFont(self.font()), gras

    def colonnes(self) -> List[str]:
        """Les titres des colonnes de chiffres, dans l'ordre affiché (contrôle hors écran)."""
        return [t for t, _w in self._colonnes()]

    def _colonnes(self) -> List[Tuple[str, int]]:
        """``[(titre, largeur), …]`` : un niveau présent par colonne, le contexte moderne s'il y en a,
        le total. Largeurs mesurées sur la police réelle (elles diffèrent entre Qt5 et Qt6)."""
        titre, chiffres, gras = self._polices()
        fm_t, fm_c = QFontMetrics(titre), QFontMetrics(gras)
        noms = [lab for _c, lab in self._niveaux] + ([LIBELLE_ECARTEES] if self._contexte else []) + [_TOTAL]
        large = fm_c.horizontalAdvance("99 999")
        # Le titre « contexte moderne » est précédé d'un carré du gris de la barre : il lui faut sa place.
        return [(n, max(fm_t.horizontalAdvance(n) + (_PASTILLE + 5 if n == LIBELLE_ECARTEES else 0), large) + _MARGE_COL)
                for n in noms]

    def sizeHint(self) -> QSize:  # noqa: N802 (signature Qt)
        return QSize(max(480, self.minimumWidth()), _ENTETE + len(self._lignes) * _RANGEE + 4)

    def _rangee_sous(self, y: float) -> Optional[LigneBilan]:
        i = int((y - _ENTETE) // _RANGEE)
        return self._lignes[i] if y >= _ENTETE and 0 <= i < len(self._lignes) else None

    def event(self, ev) -> bool:  # noqa: N802 (signature Qt)
        if ev.type() == QEvent.Type.ToolTip:
            ligne = self._rangee_sous(ev.pos().y())
            if ligne is not None:
                QToolTip.showText(ev.globalPos(), ligne.phrase(), self)
                return True
        return super().event(ev)

    # ------------------------------------------------------------------ dessin
    def paintEvent(self, _ev) -> None:  # noqa: N802 (signature Qt)
        if not self._lignes:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        police_titre, police, police_gras = self._polices()
        colonnes = self._colonnes()
        largeur_chiffres = sum(w for _t, w in colonnes)
        x_barre = _LARGEUR_LIBELLE
        largeur_barre = max(_BARRE_MIN, self.width() - x_barre - largeur_chiffres)
        droite = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        gauche = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        # En-tête : il sert de légende.
        p.setFont(police_titre)
        p.setPen(_ENCRE_DOUCE)
        p.drawText(QRectF(0, 0, _LARGEUR_LIBELLE, _ENTETE), gauche, "structure")
        x = x_barre + largeur_barre
        fm_titre = QFontMetrics(police_titre)
        for titre, w in colonnes:
            p.setPen(_ENCRE_DOUCE)
            p.drawText(QRectF(x, 0, w, _ENTETE), droite, titre)
            if titre == LIBELLE_ECARTEES:      # le gris du dernier segment des barres, dit par un carré
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_GRIS_ECARTEES)
                xc = x + w - fm_titre.horizontalAdvance(titre) - _PASTILLE - 5
                p.drawRoundedRect(QRectF(xc, (_ENTETE - _PASTILLE) / 2, _PASTILLE, _PASTILLE), 2, 2)
            x += w

        for i, (ligne, base) in enumerate(zip(self._lignes, self._bases)):
            y = _ENTETE + i * _RANGEE
            p.setPen(QPen(_FILET, 1))
            p.drawLine(0, int(y), self.width(), int(y))
            # Pastille de la couleur de la couche, puis le libellé.
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(*base))
            p.drawRoundedRect(QRectF(0, y + (_RANGEE - _PASTILLE) / 2, _PASTILLE, _PASTILLE), 2, 2)
            p.setFont(police_gras)
            p.setPen(_ENCRE)
            libelle = QFontMetrics(police_gras).elidedText(
                ligne.label, Qt.TextElideMode.ElideRight, _LARGEUR_LIBELLE - _PASTILLE - 16)
            p.drawText(QRectF(_PASTILLE + 6, y, _LARGEUR_LIBELLE - _PASTILLE - 10, _RANGEE), gauche, libelle)
            # Barre en parts : toute la largeur, quelle que soit la taille de la structure.
            yb = y + (_RANGEE - _BARRE_H) / 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_FOND_BARRE)
            p.drawRoundedRect(QRectF(x_barre, yb, largeur_barre - 8, _BARRE_H), 3, 3)
            total = ligne.total
            parts = [(teinte_niveau(base, cat), n) for cat, n in ligne.par_niveau() if n > 0]
            if ligne.n_ecartees > 0:
                parts.append((_GRIS_ECARTEES, ligne.n_ecartees))
            xs = float(x_barre)
            for k, (couleur, n) in enumerate(parts):
                seg = (largeur_barre - 8) * n / total if total else 0.0
                p.setBrush(couleur)
                p.drawRect(QRectF(xs, yb, seg, _BARRE_H))
                xs += seg
                if k < len(parts) - 1:
                    p.setPen(QPen(QColor("#ffffff"), 1))
                    p.drawLine(QRectF(xs, yb, 0, _BARRE_H).topLeft(), QRectF(xs, yb, 0, _BARRE_H).bottomLeft())
                    p.setPen(Qt.PenStyle.NoPen)
            # Les chiffres, en colonnes.
            par_niveau = dict(ligne.par_niveau())
            x = x_barre + largeur_barre
            for titre, w in colonnes:
                if titre == _TOTAL:
                    valeur, police_c, encre = total, police_gras, _ENCRE
                elif titre == LIBELLE_ECARTEES:
                    valeur, police_c, encre = ligne.n_ecartees, police, _ENCRE_DOUCE
                else:
                    cat = next(c for c, lab in self._niveaux if lab == titre)
                    valeur, police_c, encre = par_niveau.get(cat, 0), police, _ENCRE
                p.setFont(police_c)
                p.setPen(encre if valeur else _ENCRE_VIDE)
                p.drawText(QRectF(x, y, w, _RANGEE), droite, _nb(valeur) if valeur else "—")
                x += w
        p.end()


def legende_niveaux(lignes: Sequence[LigneBilan]) -> List[Tuple[str, str]]:
    """``[(catégorie, libellé), …]`` des niveaux présents, du plus sûr au plus douteux
    — ce sont les colonnes du tableau."""
    from ...app.services.bilan_fiabilite import NIVEAUX_DU_PLUS_SUR
    from ...app.services.fiabilite import LABELS_FR

    presents = {c for ligne in lignes for c in ligne.effectifs}
    return [(c, LABELS_FR.get(c, c)) for c in NIVEAUX_DU_PLUS_SUR if c in presents]
