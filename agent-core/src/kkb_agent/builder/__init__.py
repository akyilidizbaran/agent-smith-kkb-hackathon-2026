"""Architect rolü — lakehouse'a YAZAN taraf.

Analist okur; Architect yazar. Aynı harness, ayrık araç setleri, ayrık bağlantı.
Bu paket Architect'in LLM'siz çekirdeğidir: bir tabloya bakıp *ne olduğunu*
kanıtıyla öneren profilci ve öneriyi yayınlama kurallarıyla sınayan doğrulayıcı.

İki ilke:
- Öneri bir iddiadır, kanıt taşır; doğrulama veriyle yapılır, modele sormakla değil.
- Kanıtı olmayan alan `unknown`/`None` kalır. Sözleşme (`register_series`) zaten
  yalnız `draft` yazabiliyor ve draft seriyi Gold kullanamıyor; yanlış tahminin
  bedeli bu yüzden sıfır — ama tahmin diye yazılmış bir `stock` yine de yalan olur.
"""

from .profile import ColumnProfile, MappingProposal, SemanticsProposal, TableProfile, profile_table, propose
from .verify import Check, VerificationReport, verify_mapping

__all__ = [
    "Check",
    "ColumnProfile",
    "MappingProposal",
    "SemanticsProposal",
    "TableProfile",
    "VerificationReport",
    "profile_table",
    "propose",
    "verify_mapping",
]
