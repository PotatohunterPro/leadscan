"""Runner local da suíte (dev only).

O DSH sandbox redireciona o tempfile.mkdtemp do sistema para uma área
virtual onde o SQLite não consegue abrir arquivos. Este runner troca o
mkdtemp por uma versão que cria diretórios REAIS dentro de .test_tmp/ do
workspace, deixando a suíte rodar igual ao ambiente normal.

Cada módulo de teste roda em UM SUBPROCESSO próprio. Motivo: os arquivos
de teste definem `DATA_DIR`/`SESSION_SECRET` e chamam `db.init_db()` no
import, e `app/db.py` cacheia `DB_PATH` no primeiro import — se todos
rodassem no mesmo processo (unittest discover), o banco de um vazava para
o outro (falhas de ordem). Em subprocesso isolado cada módulo é dono do
próprio banco, como o autor de cada teste assumiu.

Uso:
  .venv\\Scripts\\python.exe run_suite_local.py            # suíte completa
  .venv\\Scripts\\python.exe run_suite_local.py test_db_funil_v2
  .venv\\Scripts\\python.exe run_suite_local.py -v test_db_funil_v2
"""

import os
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------- sandbox
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

# ---------------------------------------------------------------- descobrir
_ROOT = os.path.dirname(os.path.abspath(__file__))
_TESTS = os.path.join(_ROOT, "tests")

# bootstrap de um subprocesso: path root+tests, mkdtemp real, roda 1 módulo
_BOOTSTRAP = r'''
import os, sys, tempfile, unittest
_ROOT = r"%s"
_TESTS = r"%s"
sys.path.insert(0, _ROOT); sys.path.insert(0, _TESTS)
ws = r"%s"; os.makedirs(ws, exist_ok=True); _c = [0]
def _mkdtemp_real(suffix="", prefix="tmp", dir=None):
    b = dir or ws
    while True:
        _c[0] += 1; p = os.path.join(b, f"{prefix}{_c[0]:05d}{suffix}")
        try:
            os.makedirs(p); return p
        except FileExistsError:
            continue
tempfile.mkdtemp = _mkdtemp_real
r = unittest.TextTestRunner(verbosity=%d).run(unittest.defaultTestLoader.loadTestsFromName("%s"))
sys.exit(0 if r.wasSuccessful() else 1)
'''


def _modulos(alvos: list[str]) -> list[str]:
    """Resolve alvos para nomes de módulo top-level (test_xxx)."""
    if not alvos:
        return sorted(
            f[:-3] for f in os.listdir(_TESTS)
            if f.startswith("test_") and f.endswith(".py")
        )
    resolvidos = []
    for a in alvos:
        if a.endswith(".py"):
            a = a.replace("/", ".").replace("\\", ".")[:-3]
        if "." in a:
            a = a.rsplit(".", 1)[1]  # tests.x -> x (top-level)
        resolvidos.append(a)
    return resolvidos


def main() -> int:
    alvos = [a for a in sys.argv[1:] if not a.startswith("-")]
    verboso = "-v" in sys.argv[1:] or "--verbose" in sys.argv[1:]
    falhas = []
    for mod in _modulos(alvos):
        codigo = _BOOTSTRAP % (_ROOT, _TESTS, _WS_TMP, 2 if verboso else 1, mod)
        proc = subprocess.run([sys.executable, "-c", codigo], cwd=_ROOT)
        if proc.returncode != 0:
            falhas.append(mod)
    if falhas:
        print(f"\nFALHAS em {len(falhas)} módulo(s): {', '.join(falhas)}")
        return 1
    print(f"\nSuíte completa: todos os módulos OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
