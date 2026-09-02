"""Runner local da suíte (dev only).

O DSH sandbox redireciona o tempfile.mkdtemp do sistema para uma área
virtual onde o SQLite não consegue abrir arquivos. Este runner troca o
mkdtemp por uma versão que cria diretórios REAIS dentro de .test_tmp/ do
workspace, deixando a suíte rodar igual ao ambiente normal.

Uso:
  .venv\\Scripts\\python.exe run_suite_local.py            # suíte completa
  .venv\\Scripts\\python.exe run_suite_local.py test_db_funil_v2
"""

import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------- sandbox
_orig_mkdtemp = tempfile.mkdtemp
_WS_TMP = os.path.abspath(os.path.join(os.path.dirname(__file__), ".test_tmp"))
os.makedirs(_WS_TMP, exist_ok=True)
_CONTADOR = [0]


def _mkdtemp_real(suffix="", prefix="tmp", dir=None):
    """Substituto de tempfile.mkdtemp que usa um diretório real no workspace."""
    base = dir or _WS_TMP
    os.makedirs(base, exist_ok=True)
    while True:
        _CONTADOR[0] += 1
        caminho = os.path.join(base, f"{prefix}{_CONTADOR[0]:05d}{suffix}")
        try:
            os.makedirs(caminho)
            return caminho
        except FileExistsError:
            continue


tempfile.mkdtemp = _mkdtemp_real

# ------------------------------------------------------------------ suite
def main() -> int:
    alvos = [a for a in sys.argv[1:] if not a.startswith("-")]
    verboso = "-v" in sys.argv[1:] or "--verbose" in sys.argv[1:]
    if alvos:
        # aceita nomes de módulo (test_db_funil_v2) ou arquivos (tests/x.py)
        modulos = []
        for a in alvos:
            if a.endswith(".py"):
                a = a.replace("/", ".").replace("\\", ".")[:-3]
            if not a.startswith("tests."):
                a = "tests." + a
            modulos.append(a)
        suite = unittest.defaultTestLoader.loadTestsFromNames(modulos)
    else:
        suite = unittest.defaultTestLoader.discover("tests")
    resultado = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if resultado.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())