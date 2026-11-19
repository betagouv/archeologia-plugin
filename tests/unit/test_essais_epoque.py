"""Les couches de la carte d'état-major à l'essai portent l'époque de la carte (2026-11-19).

Elles étaient datées « aujourd'hui, 2020 » : mal placées sur la frise et mal nommées dans l'arbre des couches,
alors que l'occupation du sol de la même carte, au catalogue, porte 1820-1866.
"""
import json
from pathlib import Path

DONNEES = Path(__file__).resolve().parents[2] / "data" / "fonds_publics"


def _liste(nom):
    d = json.loads((DONNEES / nom).read_text(encoding="utf-8"))
    return d.get("fonds", d) if isinstance(d, dict) else d


def test_etat_major_a_l_essai_date_comme_la_carte():
    carte = next(f for f in _liste("fonds.json") if f["id"] == "etat_major_vecteur")
    essais = [f for f in _liste("essais.json") if f["typename"].startswith("BDCARTO_ETAT-MAJOR")]
    assert len(essais) == 3
    for f in essais:
        assert (f["epoque"], f["debut"], f["fin"]) == (carte["epoque"], carte["debut"], carte["fin"]), f["id"]
