"""Page « Fonds de carte » de l'onglet « Catalogue des flux ».

Les fonds publics de l'IGN (cartes anciennes, photos aériennes, Plan IGN…) sont les mêmes partout en
France : une ligne par fond, posée sur un axe du temps, une case à cocher, et **un seul geste** qui
ajoute le lot au projet. Ensuite tout se passe dans l'arbre des couches de QGIS : les fonds vont dans
un groupe **mutuellement exclusif** placé au-dessus des images du relief et sous les détections, si
bien que cocher une autre époque décoche la précédente.

Aucun fond n'est coché au départ. Un fond local (front de Verdun, état-major des environs de Paris)
dit sa zone ; la page ne fait aucune requête réseau.

Logique pure : :mod:`app.services.fonds_publics`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QPainter
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..app.services import fonds_publics as fp
from .widgets.info_button import COTE as INFO_COTE
from .widgets.info_button import InfoButton
from .widgets.vignette import pixmap_ajuste

W_CASE, W_VIGNETTE, W_EPOQUE = 20, 28, 78
W_PROVENANCE = 160
MIN_TITRE, MIN_FRISE = 190, 200
#: Bleu du thème, bordures et texte atténué (mêmes tokens que v2.qss).
BLEU, TRAIT, DOUX = "#2b79c2", "#c4c4c4", "#4f5a66"
#: La zone d'un fond local, et l'étiquette « à l'essai » (une source sans fiche pour l'instant).
OCRE = "#9a6a12"
STYLE_ESSAI = "background-color:#f7ecd6;color:#8a5a0a;font-weight:normal;font-size:10px"
#: Nombre de thèmes dépliés à l'ouverture de la page.
THEMES_OUVERTS = 2
ANNEES = (1750, 1800, 1850, 1900, 1950, 2000)
CONSIGNE = ("Cartes anciennes et photos aériennes publiques, les mêmes partout en France. "
            "Cochez les fonds voulus, puis ajoutez-les au projet.")


class _Frise(QWidget):
    """Une barre d'époque sur l'axe commun ; sans fond, c'est l'en-tête (années)."""

    def __init__(self, fond: Optional[fp.Fond] = None, parent=None):
        super().__init__(parent)
        self._fond = fond
        self.setMinimumWidth(MIN_FRISE)
        self.setFixedHeight(14)

    def paintEvent(self, _event) -> None:  # noqa: N802 (signature Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        a0, a1 = fp.AXE
        if self._fond is None:
            police = QFont(self.font())
            police.setPointSizeF(max(6.0, police.pointSizeF() - 1.5))
            p.setFont(police)
            p.setPen(QColor(DOUX))
            for annee in ANNEES:
                x = (annee - a0) / (a1 - a0) * w
                p.drawText(int(x), int(h) - 3, str(annee))
            p.end()
            return
        p.setPen(QColor(TRAIT))
        for annee in ANNEES:
            x = (annee - a0) / (a1 - a0) * w
            p.drawLine(int(x), 2, int(x), int(h) - 2)
        pos = fp.position(self._fond)
        if pos is not None:
            debut, fin = pos
            largeur = max(5.0, (fin - debut) * w)
            x = min(debut * w, w - largeur)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(BLEU))
            p.drawRoundedRect(QRectF(x, 3.0, largeur, h - 6.0), 3.0, 3.0)
        p.end()


class _Ligne(QFrame):
    """Un fond : case, vignette, époque, titre (et zone), provenance, puis sa barre sur la frise — ou, pour
    une donnée vectorielle, la phrase qui dit ce qu'on y lit (elles datent toutes d'aujourd'hui)."""

    def __init__(self, fond: fp.Fond, vignette: Path, parent=None):
        super().__init__(parent)
        self.fond = fond
        self.texte = fp.texte_recherche(fond)
        self.setObjectName("FondLigne")
        self.setProperty("sorte", "objets" if fond.objets else "images")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 2, 12, 2)
        lay.setSpacing(10)

        self.case = QCheckBox()
        self.case.setFixedWidth(W_CASE)
        self.case.setChecked(False)     # rien de coché au départ : c'est l'utilisateur qui choisit
        lay.addWidget(self.case)

        img = QLabel()
        img.setObjectName("FondVignette")
        if fond.objets and fond.couleur:
            # La vignette d'un objet porte la couleur de ses contours : on la retrouve dans QGIS.
            img.setStyleSheet(f"border: 2px solid {fond.couleur};")
        img.setFixedSize(W_VIGNETTE, W_VIGNETTE)
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = pixmap_ajuste(str(vignette), W_VIGNETTE - 2, dpr=self.devicePixelRatioF())
        if not pix.isNull():
            img.setPixmap(pix)
        lay.addWidget(img)

        epoque = QLabel("" if fond.objets else fond.epoque)
        epoque.setObjectName("FondEpoque")
        epoque.setFixedWidth(W_EPOQUE)
        lay.addWidget(epoque)

        html = fond.titre
        if not fond.objets and fond.repere:
            html += "  <span style='color:%s;font-weight:normal'>repère transparent</span>" % DOUX
        if fond.essai:                      # la petite étiquette : pas encore de fiche
            html += "&nbsp; <span style='%s'>&nbsp;à l'essai&nbsp;</span>" % STYLE_ESSAI
        if fond.zone:                       # un fond local dit sa zone, sous son titre
            html += "<br><span style='color:%s;font-weight:normal;font-size:10px'>%s seulement</span>" % (OCRE, fond.zone)
        titre = QLabel(html)
        titre.setObjectName("FondTitre")
        titre.setTextFormat(Qt.TextFormat.RichText)
        titre.setMinimumWidth(MIN_TITRE)
        detail = f"{fond.detail_m:g} m par pixel au plus fin".replace(".", ",") if fond.detail_m else ""
        titre.setToolTip(" · ".join(t for t in (fond.titre, fond.source, detail, fond.couche) if t))
        lay.addWidget(titre, 3)

        self.info = InfoButton("Voir la fiche de ce fond")
        if fond.essai:                      # à l'essai : pas encore de fiche ; la place reste, les colonnes s'alignent
            politique = self.info.sizePolicy()
            politique.setRetainSizeWhenHidden(True)
            self.info.setSizePolicy(politique)
            self.info.hide()
        lay.addWidget(self.info)

        # Qui produit la donnée (IGN, BRGM, BnF…) : dit en clair et en entier.
        self.provenance = QLabel()
        self.provenance.setObjectName("FondProvenance")
        self.provenance.setFixedWidth(W_PROVENANCE)
        self.provenance.setText(fond.source)      # en entier, sur deux lignes au besoin (jamais coupé, 2026-11-12)
        self.provenance.setWordWrap(True)
        self.provenance.setToolTip(fond.source)
        lay.addWidget(self.provenance)

        if fond.objets:
            self.frise = None
            quoi = QLabel(fond.quoi)
            quoi.setObjectName("FondQuoi")
            quoi.setMinimumWidth(MIN_FRISE)
            quoi.setToolTip(fond.quoi)
            quoi.setWordWrap(True)                 # en entier, sur deux lignes au besoin
            quoi.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)   # sans élargir la ligne
            lay.addWidget(quoi, 3)
        else:
            self.frise = _Frise(fond)
            lay.addWidget(self.frise, 3)


class _Bandeau(QFrame):
    """Le bandeau d'un thème : il se replie d'un clic (ou Espace / Entrée), dit combien de sources il porte
    et combien sont cochées."""

    bascule = pyqtSignal()

    def __init__(self, theme: str, sorte: str, parent=None):
        super().__init__(parent)
        self.setObjectName("FondSection")
        self.setProperty("sorte", sorte)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.theme, self.sorte, self.ouvert = theme, sorte, False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 6)
        lay.setSpacing(10)
        self._fleche = QLabel("▸")
        self._fleche.setObjectName("FondSectionSous")
        self._fleche.setFixedWidth(10)
        lay.addWidget(self._fleche)
        t = QLabel(theme.upper())
        t.setObjectName("FondSectionTitre")
        lay.addWidget(t)
        self._compte = QLabel("")
        self._compte.setObjectName("FondSectionSous")
        lay.addWidget(self._compte, 1)
        self._coches = QLabel("")
        self._coches.setObjectName("FondSectionCoches")
        lay.addWidget(self._coches)

    def dire(self, n: int, coches: int, deplie: bool) -> None:
        sorte = "données vectorielles" if self.sorte == "objets" else "fonds de carte"
        self._fleche.setText("▾" if deplie else "▸")
        self._compte.setText(f"{n} source{'s' if n > 1 else ''} · {sorte}")
        self.dire_coches(coches)

    def dire_coches(self, coches: int) -> None:
        self._coches.setText(f"{coches} coché{'s' if coches > 1 else ''}" if coches else "")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (signature Qt)
        if event.button() == Qt.MouseButton.LeftButton:
            self.bascule.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (signature Qt)
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.bascule.emit()
        else:
            super().keyPressEvent(event)


class FondsPage(QWidget):
    """Les fonds publics, rangés par thèmes repliables, et leur ajout au projet QGIS."""

    #: Les couches de fonds du projet ont changé (ajout, retrait) : l'onglet recompte.
    couches_changees = pyqtSignal()
    #: La fiche d'un fond est demandée (bouton « i » de sa ligne) : l'assistant l'ouvre dans sa fenêtre.
    fiche_demandee = pyqtSignal(str)

    def __init__(self, plugin_root: Path, iface=None, parent=None):
        super().__init__(parent)
        self._iface = iface
        self._dossier = Path(plugin_root) / fp.CATALOGUE.parent
        self._service = ""
        self._fonds: List[fp.Fond] = []
        self._lignes: Dict[str, _Ligne] = {}
        try:
            self._service, self._fonds = fp.charger(Path(plugin_root) / fp.CATALOGUE)
        except (OSError, ValueError):
            pass                              # catalogue absent ou illisible : page vide, dite plus bas
        self._essais: List[fp.Fond] = fp.charger_essais(Path(plugin_root) / fp.ESSAIS) if self._fonds else []
        self.absentes: List[str] = []
        self.indisponibles: List[str] = []
        self._sections: List[Tuple[_Bandeau, List[str]]] = []    # (bandeau, identifiants de ses lignes)
        self._sorte = "tout"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Outils : recherche, sorte de source, et « seulement ce qui couvre la carte affichée ».
        outils = QFrame()
        outils.setObjectName("FondOutils")
        ol = QHBoxLayout(outils)
        ol.setContentsMargins(12, 6, 12, 6)
        ol.setSpacing(8)
        self._recherche = QLineEdit()
        self._recherche.setObjectName("FondRecherche")
        self._recherche.setPlaceholderText("Chercher un fond, un producteur…")
        self._recherche.setClearButtonEnabled(True)
        self._recherche.setFixedWidth(230)
        self._recherche.textChanged.connect(self.appliquer)
        ol.addWidget(self._recherche)
        for cle, libelle in (("tout", "Tout"), ("images", "Fonds de carte"), ("objets", "Données vectorielles")):
            puce = QPushButton(libelle)
            puce.setObjectName("FondPuce")
            puce.setCheckable(True)
            puce.setAutoExclusive(True)
            puce.setChecked(cle == "tout")
            puce.setCursor(Qt.CursorShape.PointingHandCursor)
            puce.clicked.connect(lambda _c=False, c=cle: self._choisir_sorte(c))
            ol.addWidget(puce)
        ol.addStretch(1)
        # Beaucoup de sources ne valent que pour une région : par défaut, la page ne montre que ce qui
        # couvre la carte affichée dans QGIS (2026-11-12). Décoché, tout est listé.
        self._ici = QCheckBox("Seulement ce qui couvre la carte affichée")
        self._ici.setObjectName("FondIci")
        self._ici.setChecked(True)
        self._ici.toggled.connect(self.appliquer)
        ol.addWidget(self._ici)
        root.addWidget(outils)

        tete = QFrame()
        tete.setObjectName("FondTete")
        tl = QHBoxLayout(tete)
        tl.setContentsMargins(12, 4, 12, 4)
        tl.setSpacing(10)
        for largeur in (W_CASE, W_VIGNETTE):
            vide = QLabel("")
            vide.setFixedWidth(largeur)
            tl.addWidget(vide)
        for libelle, largeur, poids in (("Époque", W_EPOQUE, 0), ("Fond", MIN_TITRE, 3)):
            lab = QLabel(libelle)
            lab.setObjectName("FondColonne")
            if poids:
                lab.setMinimumWidth(largeur)
            else:
                lab.setFixedWidth(largeur)
            tl.addWidget(lab, poids)
        place_info = QLabel("")
        place_info.setFixedWidth(INFO_COTE)
        tl.addWidget(place_info)
        provenance = QLabel("Provenance")
        provenance.setObjectName("FondColonne")
        provenance.setFixedWidth(W_PROVENANCE)
        tl.addWidget(provenance)
        tl.addWidget(_Frise(None), 3)
        root.addWidget(tete)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Ascenseur toujours là, et la même largeur réservée dans l'en-tête : sans cela les années
        # de l'en-tête ne tombent pas au-dessus des graduations des lignes.
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        tl.setContentsMargins(12, 4, 12 + scroll.verticalScrollBar().sizeHint().width(), 4)
        hote = QWidget()
        hote.setObjectName("FondListe")
        hl = QVBoxLayout(hote)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        for rang, (theme, objets, membres) in enumerate(fp.par_theme(self._fonds + self._essais)):
            bandeau = _Bandeau(theme, "objets" if objets else "images")
            bandeau.ouvert = rang < THEMES_OUVERTS
            bandeau.bascule.connect(lambda b=bandeau: self._basculer(b))
            self._sections.append((bandeau, [f.id for f in membres]))
            hl.addWidget(bandeau)
            for fond in membres:
                ligne = _Ligne(fond, self._dossier / fond.vignette if fond.vignette else Path())
                ligne.case.toggled.connect(self._sync_bouton)
                ligne.info.clicked.connect(lambda _c=False, i=fond.id: self.fiche_demandee.emit(i))
                self._lignes[fond.id] = ligne
                hl.addWidget(ligne)
        # Les sources d'ailleurs : dites en bas de la liste, avec le moyen de les montrer.
        self._ailleurs = QPushButton("")
        self._ailleurs.setObjectName("FondAilleurs")
        self._ailleurs.setFlat(True)
        self._ailleurs.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ailleurs.clicked.connect(lambda: self._ici.setChecked(False))
        self._ailleurs.hide()
        hl.addWidget(self._ailleurs)
        self._rien = QLabel("Aucune source ne correspond.")
        self._rien.setObjectName("VisuEmpty")
        self._rien.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rien.hide()
        hl.addWidget(self._rien)
        if not self._fonds:
            vide = QLabel("Le catalogue des fonds de carte est introuvable dans cette installation.")
            vide.setObjectName("VisuEmpty")
            vide.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hl.addWidget(vide)
        hl.addStretch(1)
        scroll.setWidget(hote)
        root.addWidget(scroll, 1)

        pied = QFrame()
        pied.setObjectName("FondPied")
        pl = QHBoxLayout(pied)
        pl.setContentsMargins(16, 8, 16, 8)
        pl.setSpacing(12)
        self._message = QLabel(CONSIGNE)
        self._message.setObjectName("VisuWallMeta")
        self._message.setWordWrap(True)
        pl.addWidget(self._message, 1)
        # Demande du 2026-11-13 : repartir de zéro d'un geste, y compris pour les cases des thèmes repliés.
        self._decocher = QPushButton("Tout décocher")
        self._decocher.setObjectName("SecondButton")
        self._decocher.setCursor(Qt.CursorShape.PointingHandCursor)
        self._decocher.setToolTip("Décoche tous les fonds, y compris ceux des thèmes repliés. "
                                  "Ce qui est déjà dans le projet QGIS n'est pas retiré")
        self._decocher.clicked.connect(self.tout_decocher)
        pl.addWidget(self._decocher)
        self._bouton = QPushButton("")
        self._bouton.setObjectName("VisuPrimaryBtn")
        self._bouton.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bouton.clicked.connect(self._sur_ajout)
        pl.addWidget(self._bouton)
        root.addWidget(pied)

        self.appliquer()
        self._sync_bouton()

    # ------------------------------------------------------------- thèmes, recherche, fonds locaux

    def _emprise_carte(self) -> Optional[Tuple[float, float, float, float]]:
        """La carte affichée dans QGIS, en lon/lat ; ``None`` sans QGIS de bureau ou sur un projet vide
        (rien n'est alors masqué)."""
        if self._iface is None:
            return None
        try:
            from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject

            canevas = self._iface.mapCanvas()
            if not QgsProject.instance().mapLayers():
                return None
            vers = QgsCoordinateTransform(canevas.mapSettings().destinationCrs(),
                                          QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
            r = vers.transformBoundingBox(canevas.extent())
            return r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()
        except Exception:  # noqa: BLE001 — une carte illisible ne doit pas vider la page
            return None

    def _choisir_sorte(self, sorte: str) -> None:
        self._sorte = sorte
        self.appliquer()

    def _basculer(self, bandeau: _Bandeau) -> None:
        bandeau.ouvert = not bandeau.ouvert
        self.appliquer()

    def ouvrir_theme(self, theme: str, objets: bool, ouvert: bool = True) -> Optional[_Bandeau]:
        """Déplie (ou replie) un thème ; rend son bandeau, ``None`` s'il n'existe pas."""
        for bandeau, _ids in self._sections:
            if bandeau.theme == theme and (bandeau.sorte == "objets") == objets:
                bandeau.ouvert = ouvert
                self.appliquer()
                return bandeau
        return None

    def appliquer(self, *_args) -> int:
        """Montre les lignes qui passent la recherche, la sorte choisie et la carte affichée, dans les thèmes
        dépliés (une recherche déplie tout). Rend le nombre de sources d'ailleurs mises de côté ; une
        source mise de côté par la carte est décochée."""
        emprise = self._emprise_carte() if self._ici.isChecked() else None
        mots = self._recherche.text().strip().lower()
        ailleurs = total = 0
        for bandeau, ids in self._sections:
            n = coches = 0
            for ident in ids:
                ligne = self._lignes[ident]
                garde = (self._sorte in ("tout", bandeau.sorte)) and (not mots or mots in ligne.texte)
                if garde and not fp.couvre(ligne.fond, emprise):
                    ailleurs += 1
                    garde = False
                    ligne.case.setChecked(False)
                n += garde
                coches += garde and ligne.case.isChecked()
                ligne.setVisible(garde and (bandeau.ouvert or bool(mots)))
            bandeau.setVisible(n > 0)
            bandeau.dire(n, coches, bandeau.ouvert or bool(mots))
            total += n
        self._ailleurs.setVisible(ailleurs > 0)
        self._ailleurs.setText(f"{ailleurs} source{'s ne couvrent' if ailleurs > 1 else ' ne couvre'} pas la carte "
                               "affichée dans QGIS. Les montrer")
        self._rien.setVisible(bool(self._fonds) and total == 0 and ailleurs == 0)
        return ailleurs

    def showEvent(self, event) -> None:  # noqa: N802 (signature Qt)
        super().showEvent(event)
        self.appliquer()

    # ------------------------------------------------------------- état

    def coches(self) -> List[fp.Fond]:
        return [f for f in self._fonds + self._essais if self._lignes[f.id].case.isChecked()]

    def tout_decocher(self) -> None:
        """Décoche toutes les lignes, visibles ou non ; le projet QGIS n'est pas touché."""
        for ligne in self._lignes.values():
            ligne.case.setChecked(False)

    def _sync_bouton(self, *_args) -> None:
        coches = self.coches()
        n = len(coches)
        pluriel = "s" if n > 1 else ""
        self._bouton.setText(f"Ajouter {n} fond{pluriel} au projet QGIS" if n else "Aucun fond coché")
        self._bouton.setEnabled(n > 0)
        self._decocher.setVisible(n > 0)
        # Le rappel du choix : ce qui est coché se lit ici, même dans un thème replié.
        self._message.setText("Cochés : " + " · ".join(f"{f.titre} {f.epoque}".strip() if not f.objets else f.titre
                                                       for f in coches) if n else CONSIGNE)
        # Le compte « N cochés » de chaque bandeau suit la case, sans recalculer les lignes visibles.
        for bandeau, ids in self._sections:
            bandeau.dire_coches(sum(1 for i in ids if self._lignes[i].case.isChecked()))

    def corps_fiche(self, fond_id: str):
        """``(corps, titre)`` des fiches des fonds, ouvertes sur ``fond_id``. Imports et lectures
        différés : rien n'est chargé tant qu'aucune fiche n'est demandée."""
        from ..app.services.carte_zones import charger as charger_carte
        from .dialogs.fond_info_dialog import corps_fiche_fond

        racine = self._dossier.parents[1]
        return (corps_fiche_fond(self._fonds, fp.charger_fiches(racine / fp.FICHES),
                                 fp.charger_couvertures(racine / fp.COUVERTURE), self._dossier,
                                 charger_carte(racine), fond_id),
                "Fonds de carte")

    # ------------------------------------------------ projet QGIS

    @staticmethod
    def presents() -> Dict[str, str]:
        """``id de fond → id de couche`` des fonds déjà dans le projet (reconnus à leur propriété)."""
        from qgis.core import QgsProject

        out = {}
        for lid, couche in QgsProject.instance().mapLayers().items():
            fond_id = couche.customProperty(fp.PROPRIETE)
            if fond_id:
                out[str(fond_id)] = lid
        return out

    def _groupe(self, nom: str):
        """Le groupe, créé s'il manque : sous « Structures », au-dessus de tout le reste (le relief)."""
        from qgis.core import QgsProject

        from ..app.services.finalize_service import GROUPE_STRUCTURES

        racine = QgsProject.instance().layerTreeRoot()
        groupe = racine.findGroup(nom)
        if groupe is not None:
            return groupe
        # Ordre de haut en bas : Structures, Données vectorielles, Repères, Fonds de carte, puis le relief.
        ordre = [GROUPE_STRUCTURES, fp.GROUPE_CONTEXTE, fp.GROUPE_OBJETS, fp.GROUPE_REPERES, fp.GROUPE_FONDS]
        noms = [n.name() for n in racine.children()]
        rang = ordre.index(nom)
        avant = [g for g in ordre[:rang] if g in noms]
        apres = [g for g in ordre[rang + 1:] if g in noms]
        if avant:
            index = noms.index(avant[-1]) + 1
        elif apres:
            index = noms.index(apres[0])
        else:
            index = 0
        groupe = racine.insertGroup(index, nom)
        if nom == fp.GROUPE_FONDS:
            groupe.setIsMutuallyExclusive(True)   # un seul fond visible : l'arbre devient la frise
        return groupe

    def ajouter(self) -> Tuple[int, int]:
        """Ajoute les fonds cochés au projet, **décochés**. Rend ``(ajoutés, déjà présents)``."""
        return self.ajouter_fonds(self.coches())

    def ajouter_contexte_moderne(self, zone=None, gpkg=None) -> Tuple[int, int]:
        """Les données vectorielles du contexte moderne (``fp.CONTEXTE_MODERNE``) : **toutes** ajoutées,
        rangées par famille dans le groupe « Contexte moderne », cochées pour celles que la sélection
        retient — les autres restent là, décochées, à cocher au besoin. Appelé par le bouton de fin de
        traitement. ``zone`` = ``(QgsRectangle, système)`` de ce qui est étudié : une donnée qui n'y a aucun
        objet n'est pas ajoutée (2026-11-12 : pas de « Pistes d'aérodrome » vide dans l'arbre) ; son titre va
        dans ``self.absentes``.

        ``gpkg`` (2026-11-13) : le fichier ``livrable/contexte/contexte_moderne.gpkg`` du traitement. Seules
        les données qu'il contient sont ajoutées, lues dans ce fichier : aucun appel au service, donc aucune
        attente. Les autres familles restent au Catalogue des flux."""
        voulus = fp.couches_contexte(self._fonds)
        locales = {}
        if gpkg is not None:
            from ..app.services.contexte_gpkg import COUCHE_PAR_FOND

            locales = {ident: f"{gpkg}|layername={couche}" for ident, couche in COUCHE_PAR_FOND.items()}
            voulus = [(g, f, v) for g, f, v in voulus if f.id in locales]
        return self.ajouter_fonds([f for _g, f, _v in voulus], visibles={f.id for _g, f, v in voulus if v},
                                  familles={f.id: g for g, f, _v in voulus}, zone=zone, locales=locales)

    @staticmethod
    def _presente(couche, fond: fp.Fond, zone) -> bool:
        """Vrai si la donnée a au moins un objet dans la zone étudiée (``(rectangle, système)``). Une question
        sans réponse (service muet) vaut « présente » : on n'écarte que ce dont on sait qu'il n'y a rien.
        ponytail: la lecture s'arrête au premier objet reçu, mais une donnée filtrée au dessin (ronds-points,
        monuments) est lue jusqu'au premier qui passe le filtre ; à borner si une zone immense sans rond-point
        se présente."""
        from qgis.core import (QgsCoordinateTransform, QgsExpression, QgsExpressionContext,
                               QgsExpressionContextUtils, QgsFeatureRequest, QgsProject)

        try:
            rect, scr = zone
            ici = QgsCoordinateTransform(scr, couche.crs(), QgsProject.instance()).transformBoundingBox(rect)
            # ⚠ Jamais ``setLimit(1)`` : le service rend alors un objet que QGIS écarte ensuite, et la réponse
            # est « rien » à tort (mesuré : 53 cours d'eau dans la zone, 0 trouvé). On s'arrête au premier reçu.
            demande = QgsFeatureRequest().setFilterRect(ici)
            # Le filtre s'évalue sur le poste, jamais au service (2026-11-18) : sous QGIS 4, la Géoplateforme ne
            # rend rien au filtre envoyé, et les ronds-points étaient déclarés absents à tort (18 dans la zone).
            filtre = QgsExpression(fond.filtre) if fond.filtre else None
            contexte = QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(couche))
            trouve = False
            for objet in couche.getFeatures(demande):
                if filtre is None:
                    trouve = True
                    break
                contexte.setFeature(objet)
                if filtre.evaluate(contexte):
                    trouve = True
                    break
            return trouve or bool(couche.dataProvider().error().summary())
        except Exception:  # noqa: BLE001 — dans le doute, la donnée est ajoutée
            return True

    def ajouter_fonds(self, fonds, visibles=frozenset(), familles=None, zone=None, locales=None) -> Tuple[int, int]:
        """Ajoute ces fonds au projet, décochés sauf ``visibles``. Rend ``(ajoutés, déjà présents)``.
        ``familles`` (``id → famille``) : les range dans un sous-groupe de « Contexte moderne », dans
        l'ordre reçu, au lieu des groupes du catalogue. ``locales`` (``id → source OGR``) : ces fonds sont
        lus dans un fichier du poste au lieu du service ; une couche absente du fichier n'est pas ajoutée."""
        locales = locales or {}
        from qgis.core import QgsProject, QgsRasterLayer, QgsRectangle

        projet = QgsProject.instance()
        presents = self.presents()
        rang = {f.id: i for i, f in enumerate(self._fonds + self._essais)}
        ajoutes = deja = 0
        self.absentes: List[str] = []           # titres des données sans objet dans ``zone``
        self.indisponibles: List[str] = []      # titres des données dont le service n'a pas répondu
        for fond in fonds:
            if fond.id in presents:
                deja += 1
                continue
            if fond.objets:
                couche = self._couche_objets(fond, locales.get(fond.id))
            else:
                couche = QgsRasterLayer(fp.uri_couche(self._service, fond), fond.nom_couche, "wms")
            if couche is None or not couche.isValid():
                self.indisponibles.append(fond.titre)   # dit à l'utilisateur, jamais écarté en silence
                continue
            if fond.id in locales:
                pass                                    # lue dans le fichier du traitement : rien à demander
            elif zone is not None and fond.objets and not self._presente(couche, fond, zone):
                self.absentes.append(fond.titre)        # rien de tel dans la zone étudiée : pas ajoutée
                continue
            if not fond.objets:
                couche.setExtent(QgsRectangle(*fp.emprise_3857(fond)))
            couche.setCustomProperty(fp.PROPRIETE, fond.id)
            legende = self._dossier / fond.legende
            if fond.legende and legende.is_file():
                couche.setLegendPlaceholderImage(str(legende))   # la légende officielle, sous la couche
            projet.addMapLayer(couche, False)
            if familles:
                parent = self._groupe(fp.GROUPE_CONTEXTE)
                groupe = parent.findGroup(familles[fond.id])
                if groupe is None:
                    groupe = parent.addGroup(familles[fond.id])
                    groupe.setExpanded(False)
                noeud = groupe.addLayer(couche)
                noeud.setItemVisibilityChecked(fond.id in visibles)
                noeud.setExpanded(False)
                ajoutes += 1
                continue
            groupe = self._groupe(fp.GROUPE_OBJETS if fond.objets else
                                  fp.GROUPE_REPERES if fond.repere else fp.GROUPE_FONDS)
            # Ordre chronologique du catalogue, quel que soit l'ordre des ajouts successifs.
            avant = sum(1 for n in groupe.findLayers()
                        if n.layer() is not None
                        and rang.get(str(n.layer().customProperty(fp.PROPRIETE)), -1) < rang[fond.id])
            noeud = groupe.insertLayer(avant, couche)
            noeud.setItemVisibilityChecked(fond.id in visibles)
            noeud.setExpanded(False)              # légende repliée : certaines font plusieurs écrans
            ajoutes += 1
        if ajoutes:
            self.couches_changees.emit()
        return ajoutes, deja

    @staticmethod
    def _couche_objets(fond: fp.Fond, locale: str = ""):
        """Un vecteur de la Géoplateforme, chargé en direct par QGIS sur la seule zone affichée, dessiné
        en contours sans remplissage (comme les détections) et muet au-delà du 1:25 000. ``locale`` : la
        source OGR d'un fichier du poste, lue à la place du service (même dessin)."""
        from qgis.core import (QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings,
                               QgsRuleBasedRenderer, QgsSingleSymbolRenderer, QgsTextBufferSettings,
                               QgsTextFormat, QgsVectorLayer, QgsVectorLayerSimpleLabeling)
        from qgis.PyQt.QtGui import QColor

        if locale:
            couche = QgsVectorLayer(locale, fond.nom_couche, "ogr")
        else:
            couche = QgsVectorLayer(fp.uri_objets(fond), fond.nom_couche, "WFS")
        if not couche.isValid() and not locale:
            # Les plateformes régionales (GéoBretagne, Géo2France) ne s'ouvrent dans QGIS qu'en version 1.1.0.
            couche = QgsVectorLayer(fp.uri_objets(fond, version="1.1.0"), fond.nom_couche, "WFS")
        if (not couche.isValid() or not couche.isSpatial()) and fond.service_objets:
            # ponytail: dernier recours, le lecteur WFS de GDAL, qui télécharge la couche entière (vu : 1 824
            # zones en Auvergne-Rhône-Alpes, dont QGIS refuse le schéma). À borner si une grosse couche y tombe.
            # Aussi pour une couche « valide » sans géométrie (2026-11-18 : quatre couches Géorisques dont
            # MapServer ne déclare pas le type ; QGIS ne les dessine jamais, GDAL si).
            couche = QgsVectorLayer(f"WFS:{fond.service_objets}|layername={fond.typename}", fond.nom_couche, "ogr")
        if not couche.isValid():
            return couche
        # La géométrie réelle de la couche quand le service la déclare ; celle du catalogue sinon
        # (un symbole de surface sur une couche de points ne dessinerait rien).
        from qgis.core import Qgis
        geometrie = {Qgis.GeometryType.Point: "point", Qgis.GeometryType.Line: "ligne",
                     Qgis.GeometryType.Polygon: "surface"}.get(couche.geometryType(), fond.geometrie)
        if geometrie == "ligne":
            symbole = QgsLineSymbol.createSimple({"line_color": fond.couleur or BLEU, "line_width": "0.4"})
        elif geometrie == "point":
            # Un point ne dit rien sans son nom (lieux-dits) : il est étiqueté de ce que donne le clic.
            symbole = QgsMarkerSymbol.createSimple({"name": "circle", "color": fond.couleur or BLEU,
                                                    "outline_color": "#ffffff", "size": "2"})
            if fond.affichage:
                etiquette = QgsPalLayerSettings()
                etiquette.fieldName = fond.affichage
                etiquette.isExpression = True
                # Halo blanc (2026-11-19) : sans lui, le texte gris foncé se perd sur le relief gris.
                texte = QgsTextFormat()
                texte.setColor(QColor("#1d1d1d"))
                halo = QgsTextBufferSettings()
                halo.setEnabled(True)
                halo.setSize(1.0)
                halo.setColor(QColor("#ffffff"))
                texte.setBuffer(halo)
                etiquette.setFormat(texte)
                couche.setLabeling(QgsVectorLayerSimpleLabeling(etiquette))
                couche.setLabelsEnabled(True)
        else:
            symbole = QgsFillSymbol.createSimple({"style": "no", "outline_color": fond.couleur or BLEU,
                                                  "outline_width": "0.4"})
        if fond.filtre:
            # Filtre appliqué au dessin, jamais envoyé au service (2026-11-12) : la Géoplateforme répond
            # « Internal Server Error » au filtre que QGIS 3.44 écrit pour les servitudes, et QGIS 4 ne
            # reçoit rien pour les ronds-points. Ce qui n'est pas dessiné n'est pas cliquable non plus.
            racine = QgsRuleBasedRenderer.Rule(None)
            racine.appendChild(QgsRuleBasedRenderer.Rule(symbole, filterExp=fond.filtre))
            couche.setRenderer(QgsRuleBasedRenderer(racine))
        else:
            couche.setRenderer(QgsSingleSymbolRenderer(symbole))
        couche.setScaleBasedVisibility(True)
        couche.setMinimumScale(fp.ECHELLE_MIN_OBJETS)
        if fond.affichage:
            couche.setDisplayExpression(fond.affichage)              # ce que montre l'identification
            couche.setMapTipTemplate(f"[% {fond.affichage} %]")      # et le survol
        return couche

    def _sur_ajout(self) -> None:
        ajoutes, deja = self.ajouter()
        self._message.setText(fp.resume_ajout(ajoutes, deja, indisponibles=len(self.indisponibles)))

    def retirer_tout(self) -> int:
        """Retire les fonds ouverts par cette page (et eux seuls), puis leurs groupes s'ils sont vides."""
        from qgis.core import QgsProject

        projet = QgsProject.instance()
        ids = list(self.presents().values())
        if ids:
            projet.removeMapLayers(ids)
        racine = projet.layerTreeRoot()
        for nom in (fp.GROUPE_FONDS, fp.GROUPE_REPERES, fp.GROUPE_OBJETS, fp.GROUPE_CONTEXTE):
            groupe = racine.findGroup(nom)
            if groupe is not None and not groupe.findLayers():
                racine.removeChildNode(groupe)
        if ids:
            self._message.setText(CONSIGNE)
        return len(ids)
