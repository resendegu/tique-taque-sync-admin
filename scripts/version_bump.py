"""Detecta se a versão do pyproject.toml mudou em relação ao commit anterior.

Uso no workflow:

    python scripts/version_bump.py --current pyproject.toml --previous prev.toml

Escreve `chave=valor` na saída padrão (e em $GITHUB_OUTPUT, quando definido):

    changed=true|false
    version=1.2.3
    major_minor=1.2
    major=1
    previous=1.2.2

Falha com mensagem clara quando a versão nova é inválida ou menor que a
anterior — um downgrade acidental publicaria uma imagem `1.2` apontando para
código mais velho que o já publicado.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tomllib
from pathlib import Path

# MAJOR.MINOR.PATCH, com pré-lançamento opcional (1.2.3-rc.1).
SEMVER = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?$"
)


def read_version(path: Path) -> str | None:
    """Lê project.version de um pyproject.toml; None se o arquivo não existir."""
    if not path.exists():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        sys.exit(f"::error::{path} não é um TOML válido: {exc}")
    version = data.get("project", {}).get("version")
    if version is None:
        sys.exit(f"::error::{path} não tem [project].version")
    return str(version)


def parse(version: str, origin: str) -> tuple[int, int, int, str]:
    match = SEMVER.match(version)
    if not match:
        sys.exit(
            f"::error::Versão {origin} inválida: '{version}'. "
            "Use MAJOR.MINOR.PATCH (ex: 1.4.0), opcionalmente com -rc.1."
        )
    return (
        int(match["major"]),
        int(match["minor"]),
        int(match["patch"]),
        match["prerelease"] or "",
    )


def emit(pairs: dict[str, str]) -> None:
    lines = [f"{key}={value}" for key, value in pairs.items()]
    print("\n".join(lines))

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument(
        "--previous",
        type=Path,
        help="pyproject.toml do commit anterior; ausente = primeiro commit",
    )
    args = parser.parse_args(argv)

    current = read_version(args.current)
    if current is None:
        sys.exit(f"::error::{args.current} não encontrado")
    major, minor, patch, prerelease = parse(current, "atual")

    previous = read_version(args.previous) if args.previous else None

    if previous is None:
        # Sem histórico para comparar: trata como alteração para não engolir a
        # primeira publicação de um repositório novo.
        emit({
            "changed": "true",
            "version": current,
            "major_minor": f"{major}.{minor}",
            "major": str(major),
            "previous": "",
        })
        return 0

    if previous == current:
        emit({"changed": "false", "version": current, "previous": previous})
        return 0

    prev_parts = parse(previous, "anterior")
    if (major, minor, patch) < prev_parts[:3]:
        sys.exit(
            f"::error::A versão caiu de {previous} para {current}. "
            "Publicar uma versão menor confunde quem fixou a tag anterior; "
            "corrija o pyproject.toml."
        )

    emit({
        "changed": "true",
        "version": current,
        "major_minor": f"{major}.{minor}",
        "major": str(major),
        "previous": previous,
        # Pré-lançamento não deve mexer nas tags móveis `1.2` e `1`.
        "prerelease": "true" if prerelease else "false",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
