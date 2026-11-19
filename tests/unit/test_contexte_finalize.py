"""Le croisement « contexte moderne » dans la finalisation : quand il se fait, et quand il se tait."""
from pathlib import Path

from src.app.services import contexte_gpkg, finalize_service as fs


class _Narrateur:
    def __init__(self):
        self.dits = []

    def contexte_moderne(self, phrase, avertissement=False):
        self.dits.append((phrase, avertissement))


class _Reporter:
    def info(self, m):
        pass


def _appel(tmp_path, cv_cfg, outcome="success", stats=None, marquer=None, monkeypatch=None):
    det = tmp_path / "detections"
    det.mkdir(exist_ok=True)
    if marquer is not None:
        monkeypatch.setattr(contexte_gpkg, "marquer", marquer)
    n = _Narrateur()
    res = fs._contexte_moderne(det, cv_cfg, stats or [], outcome, "EPSG:2154", _Reporter(), n, None)
    return res, n


def test_option_coupee_ou_absente_rien_ne_se_passe(tmp_path, monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("ne doit pas être appelé")
    for cfg in ({}, {"contexte_moderne": False}, None):
        res, n = _appel(tmp_path, cfg, marquer=interdit, monkeypatch=monkeypatch)
        assert res is None and n.dits == []


def test_traitement_en_echec_ou_annule_rien_ne_se_passe(tmp_path, monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("ne doit pas être appelé")
    for outcome in ("cancelled", "error"):
        res, _ = _appel(tmp_path, {"contexte_moderne": True}, outcome=outcome, marquer=interdit, monkeypatch=monkeypatch)
        assert res is None


def test_option_cochee_le_croisement_est_fait_et_narre(tmp_path, monkeypatch):
    vus = {}

    def faux(det_dir, lire_json, **k):
        vus["det"], vus["crs"] = Path(det_dir), k["crs"]
        return contexte_gpkg.Bilan(total=10, marquees=2, informees=3, source="s")
    res, n = _appel(tmp_path, {"contexte_moderne": True}, marquer=faux, monkeypatch=monkeypatch)
    assert vus == {"det": tmp_path / "detections", "crs": "EPSG:2154"}
    assert res.en_dict()["marquees"] == 2
    assert n.dits == [("Contexte moderne : sur 10 détections, 2 en contexte moderne (catégorie grise, décochée), "
                       "3 avec une information de contexte.", False)]


def test_une_erreur_est_dite_jamais_levee(tmp_path, monkeypatch):
    def casse(*a, **k):
        raise PermissionError("verrouillé")
    res, n = _appel(tmp_path, {"contexte_moderne": True}, marquer=casse, monkeypatch=monkeypatch)
    assert res.motif.startswith("Contexte moderne non vérifié (PermissionError")
    assert n.dits[0][1] is True


def test_les_trois_runners_transmettent_l_annulation():
    racine = Path(__file__).resolve().parents[2]
    for nom in ("existing_mnt_runner", "existing_rvt_runner", "ign_local_runner"):
        texte = (racine / "src/app/runners" / f"{nom}.py").read_text(encoding="utf-8")
        assert "cancel_check=cancel.is_cancelled" in texte, nom
