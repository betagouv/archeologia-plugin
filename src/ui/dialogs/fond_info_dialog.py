"""Fiche d'un fond de carte public — ce que l'archéologue lit avant de l'ajouter au projet.

Pendant, pour l'onglet « Catalogue des flux », de :mod:`indice_info_dialog` : même gabarit, mêmes
helpers de mise en page, même fenêtre (:class:`FicheDialog`). Elle répond à cinq questions :

1. **Qu'est-ce que je vais voir ?** — un aperçu du fond et la lecture de l'image ;
2. **Où existe-t-il ?** — la carte de France de sa couverture réelle, mesurée ;
3. **À quoi ça sert ?** — l'usage en prospection ;
4. **Qu'est-ce que ça ne montre pas ?** — les limites, dites franchement ;
5. **D'où ça sort ?** — comment le fond a été fait, et les sources.

Les données viennent du module PUR :mod:`app.services.fonds_publics` ; le contour de la France est
celui du bandeau « Appris sur » (:mod:`app.services.carte_zones`). Qt5/Qt6 : énumérés scopés.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from qgis.PyQt.QtCore import QPointF, QRectF, QSize, Qt
from qgis.PyQt.QtGui import QColor, QPainter, QPainterPath, QPen
from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ...app.services import fonds_publics as fp
from ...app.services.carte_zones import anneaux_du_pays, projection
from ..widgets.vignette import pixmap_ajuste
from .class_info_dialog import Feuilleteur, FicheDialog, _label, _puces, _separateur, _titre_bloc

_APERCU_MAX = 320     # côté max de l'aperçu, px logiques
_COTE_CARTE = 170     # côté de la carte de France, px logiques
_TERRE, _TRAIT, _COUVERT = QColor("#eef0ea"), QColor("#a3aaa3"), QColor("#2b79c2")


class CarteCouverture(QWidget):
    """La France, et en bleu les cases où le fond a réellement une image."""

    def __init__(self, couverture: Optional[fp.Couverture], data_carte: Mapping[str, Any], parent=None):
        super().__init__(parent)
        self._couverture = couverture
        self._anneaux = anneaux_du_pays(data_carte, "france")
        self.setFixedSize(_COTE_CARTE, _COTE_CARTE)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 (signature Qt)
        return self.size()

    def paintEvent(self, _ev) -> None:  # noqa: N802 (signature Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f, _l, _h = projection(self._anneaux, "france", _COTE_CARTE, _COTE_CARTE)
        pays = QPainterPath()
        for anneau in self._anneaux:
            pts = [QPointF(*f(lon, lat)) for lon, lat in anneau]
            if len(pts) > 2:
                pays.moveTo(pts[0])
                for q in pts[1:]:
                    pays.lineTo(q)
                pays.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_TERRE)
        p.drawPath(pays)
        if self._couverture is not None:
            # Les cases débordent du trait de côte : on les rogne au contour du pays.
            p.save()
            p.setClipPath(pays)
            p.setBrush(_COUVERT)
            for x, y in self._couverture.cases:
                ouest, sud, est, nord = fp.bornes_case(self._couverture.zoom, x, y)
                (x0, y0), (x1, y1) = f(ouest, nord), f(est, sud)
                # Un fond local tient dans une ou deux cases : on lui garde une taille visible.
                p.drawRect(QRectF(x0 - 0.3, y0 - 0.3, max(x1 - x0, 2.0) + 0.6, max(y1 - y0, 2.0) + 0.6))
            p.restore()
        p.setPen(QPen(_TRAIT, 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(pays)
        p.end()


class _CorpsFiche(QWidget):
    def __init__(self, fond: fp.Fond, fiche: Optional[fp.FicheFond], couverture: Optional[fp.Couverture],
                 dossier: Path, data_carte: Mapping[str, Any], parent=None):
        super().__init__(parent)
        fiche = fiche or fp.FicheFond()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 18)
        lay.setSpacing(12)

        titre = QHBoxLayout()
        titre.setSpacing(10)
        titre.addWidget(_label(fond.titre, "FicheTitre", wrap=False))
        titre.addWidget(_label(f"{fond.epoque} · {fond.source}", "FicheId", wrap=False))
        titre.addStretch(1)
        lay.addLayout(titre)
        if fiche.resume:
            lay.addWidget(_label(fiche.resume, "FicheResume"))

        image = dossier / (fond.apercu or fond.vignette)
        pix = pixmap_ajuste(str(image), _APERCU_MAX, dpr=self.devicePixelRatioF())
        if not pix.isNull():
            cadre = QLabel()
            cadre.setObjectName("FicheVignette")
            cadre.setPixmap(pix)
            cadre.setFixedSize(_APERCU_MAX + 2, _APERCU_MAX + 2)
            cadre.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(cadre)
            lay.addWidget(_label(f"Extrait du fond, {fond.lieu_apercu}. Source : {fond.source}.", "FicheLegende"))
        if fiche.lire:
            lay.addWidget(_titre_bloc("Ce que montre le fond"))
            lay.addWidget(_label(fiche.lire, "FicheTexte"))

        # — où le fond existe : la carte de sa couverture mesurée —
        lay.addWidget(_separateur())
        lay.addWidget(_titre_bloc("Où ce fond existe"))
        bande = QHBoxLayout()
        bande.setSpacing(14)
        bande.addWidget(CarteCouverture(couverture, data_carte), 0, Qt.AlignmentFlag.AlignTop)
        mots = []
        if couverture is not None:
            mots.append(f"<b>{couverture.phrase}</b>" + (f" : {fond.zone}." if fond.local else "."))
            mots.append("En bleu, les endroits où le fond a une image. Mesuré auprès de l'IGN, "
                        "par cases d'environ 25 km.")
        else:
            mots.append("Couverture non mesurée.")
        if fond.detail_m:
            detail = f"{fond.detail_m:g}".replace(".", ",")
            mots.append(f"Au plus fin, un pixel du fond vaut {detail} m sur le terrain.")
        texte = _label("<br><br>".join(mots), "FicheTexte")
        texte.setTextFormat(Qt.TextFormat.RichText)
        bande.addWidget(texte, 1)
        lay.addLayout(bande)

        for titre_bloc, contenu in self._blocs(fond, fiche):
            lay.addWidget(_separateur())
            lay.addWidget(_titre_bloc(titre_bloc))
            lay.addWidget(contenu)
        lay.addStretch(1)

    @staticmethod
    def _references(fiche: fp.FicheFond) -> QLabel:
        lignes = []
        for r in fiche.references:
            texte = r.citation.replace("&", "&amp;").replace("<", "&lt;")
            lignes.append(f'•&nbsp;&nbsp;<a href="{r.url}">{texte}</a>' if r.url else f"•&nbsp;&nbsp;{texte}")
        lab = _label("<br>".join(lignes), "FicheTexte")
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setOpenExternalLinks(True)
        return lab

    def _blocs(self, fond: fp.Fond, f: fp.FicheFond):
        out = []
        if f.usage:
            out.append(("Dans quelle optique l'utiliser", _puces(f.usage)))
        if f.limites:
            out.append(("Ce que ce fond ne montre pas", _puces(f.limites, "FicheHorsCible")))
        if f.origine:
            out.append(("Comment il a été fait", _puces(f.origine)))
        if fond.legende:
            out.append(("Légende", _label("Ce fond porte sa légende officielle : dépliez sa couche dans l'arbre "
                                          "des couches de QGIS pour la lire.", "FicheTexte")))
        if f.references:
            out.append(("Sources", self._references(f)))
        if not f.est_complete:
            out.append(("Fiche incomplète", _label("Blocs à écrire pour ce fond : " + ", ".join(f.manques)
                                                    + " (data/fonds_publics/fiches.json).", "FicheManque")))
        return out


def corps_fiche_fond(fonds: Sequence[fp.Fond], fiches: Mapping[str, fp.FicheFond],
                     couvertures: Mapping[str, fp.Couverture], dossier: Path,
                     data_carte: Mapping[str, Any], id_actif: str = "") -> QWidget:
    """Les fiches des fonds, à feuilleter dans l'ordre de la page, ouvertes sur ``id_actif``."""
    fonds = list(fonds)
    if not fonds:
        return _label("Aucune fiche disponible.", "FicheManque")
    entrees = [(f.nom_couche, f.source,
                lambda f=f: _CorpsFiche(f, fiches.get(f.id), couvertures.get(f.id), dossier, data_carte))
               for f in fonds]
    feuilleteur = Feuilleteur(entrees)
    feuilleteur.selectionner(next((i for i, f in enumerate(fonds) if f.id == id_actif), 0))
    return feuilleteur


class FondInfoDialog(FicheDialog):
    """Les fiches des fonds de carte, en dialogue (rendu hors écran)."""

    def __init__(self, fonds, fiches, couvertures, dossier, data_carte, id_actif: str = "", parent=None):
        super().__init__(corps_fiche_fond(fonds, fiches, couvertures, dossier, data_carte, id_actif),
                         "Fonds de carte", "IndiceInfoDialog", parent)
