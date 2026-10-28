"""
dados_ficticios.py — dados FALSOS para testar o ano letivo (e as telas) sem usar dado de aluno de verdade
=============================================================================
Pedido do usuário (24/10/2026): criar dados falsos, com base nos JSON do sistema, para o ano letivo de 2025, de
modo a poder testar a troca de ano letivo e a restauração dos dados de um ano.

O QUE É GERADO em dados/<ano>/ (o mesmo formato que as automações gravam)
  turmas.json                 {turma: [{N, CGM, Nome, Data Nasc., Idade, Sexo, Situação, Data Matricula}]}
  alunos.json                 cadastro completo de cada aluno (os campos que alunos.py coleta)
  funcionarios.json           funcionários do SERE (nome, cpf, funcao, rg, nome_mae, email, curso_superior, turmas)
  funcionarios_completo.json  cadastro individual de cada funcionário (pelo CPF)
  funcionarios_matriculas.json  vínculos (servidor / terceirizado / estagiário, na_escola, local do holerite...)
  pre_matricula.json          fila da pré-matrícula, cadastros dos responsáveis e situação (matriculado, aguardando...)
  _DADOS_FICTICIOS.txt        marca a pasta como fictícia (a tela avisa e deixa regenerar)
NÃO são gerados: documentos digitalizados, documentos-alunos.json, transferidos.json, alunos_fora_raio.json.

COMO PARECE FALSO DE PROPÓSITO (e é seguro)
  - nomes sorteados de listas pequenas; CPFs com os dois dígitos verificadores ERRADOS (nunca são de uma pessoa);
  - e-mails em @example.com (domínio reservado, não existe caixa) e telefones (00) 00000-xxxx;
  - os dados são sempre os mesmos para o mesmo ano (semente fixa), então os testes são repetíveis.

SEGURANÇA: se dados/<ano>/ já tem arquivos que NÃO são fictícios, nada é escrito (ValueError). Se a pasta só tem
dados fictícios (marca presente), eles são regenerados.

Uso:
    python -m src.comum.dados_ficticios --ano 2025 [--backup]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

from src.comum import paths

MARCADOR = "_DADOS_FICTICIOS.txt"
SEMENTE = 2025

PRIMEIROS_F = ["ANA", "BEATRIZ", "CLARA", "DANIELA", "ELISA", "FERNANDA", "GABRIELA", "HELENA", "ISADORA", "JULIA",
               "KAROLINE", "LARISSA", "MARINA", "NATALIA", "OLIVIA", "PAULA", "RAFAELA", "SOFIA", "TAINA", "VALENTINA"]
PRIMEIROS_M = ["ARTHUR", "BERNARDO", "CAIO", "DAVI", "EDUARDO", "FELIPE", "GUSTAVO", "HENRIQUE", "IGOR", "JOAO",
               "KAUA", "LUCAS", "MATEUS", "NICOLAS", "OTAVIO", "PEDRO", "RAFAEL", "SAMUEL", "THEO", "VICTOR"]
SOBRENOMES = ["ALMEIDA", "BARBOSA", "CARDOSO", "DIAS", "ESTEVES", "FARIAS", "GOMES", "HOLZ", "IBRAHIM", "JARDIM",
              "KOWALSKI", "LIMA", "MACHADO", "NUNES", "OLIVEIRA", "PEREIRA", "QUEIROZ", "RIBEIRO", "SANTOS", "TEIXEIRA",
              "URBANO", "VIEIRA", "WEBER", "XAVIER", "ZANELLA"]

# (turma, idade no ano, quantidade de alunos)
TURMAS_MODELO = [
    ("Infantil IV A", 4, 5), ("Infantil V A", 5, 6), ("1º Ano Integral A", 6, 7), ("1º Ano Integral B", 6, 7),
    ("2º Ano Integral A", 7, 7), ("3º Ano A", 8, 8), ("4º Ano A", 9, 8), ("5º Ano A", 10, 9),
]

# (função, curso superior, vínculo): vínculo = servidor | terceirizado | estagiario | servidor_fora (holerite em outro local)
FUNCIONARIOS_MODELO = [
    ("Gestor(a) Escolar", "Pedagogia", "servidor"), ("Diretor(a) Auxiliar", "Pedagogia", "servidor"),
    ("Pedagogo(a)", "Pedagogia", "servidor"), ("Docente", "Pedagogia", "servidor"), ("Docente", "Pedagogia", "servidor"),
    ("Docente", "Letras", "servidor"), ("Docente", "Matemática", "servidor"), ("Docente", "Educação Física", "servidor"),
    ("Docente", "Pedagogia", "servidor_fora"), ("Secretário(a) Escolar", "", "servidor"),
    ("Auxiliar de Serviços Gerais", "", "terceirizado"), ("Auxiliar de Serviços Gerais", "", "terceirizado"),
    ("Assistente Administrativo", "", "estagiario"), ("Outras funções", "", "servidor"),
]


# ───────────────────────────── blocos de geração ─────────────────────────────

def _cpf_ficticio(rng: random.Random) -> str:
    """CPF com os dois dígitos verificadores propositalmente ERRADOS (nunca é de uma pessoa real)."""
    while True:
        base = [rng.randint(0, 9) for _ in range(9)]
        if len(set(base)) == 1:
            continue
        d1 = (sum(d * w for d, w in zip(base, range(10, 1, -1))) * 10 % 11) % 10
        d2 = (sum(d * w for d, w in zip(base + [d1], range(11, 1, -1))) * 10 % 11) % 10
        errado = ((d1 + 1) % 10, d2)
        n = "".join(map(str, base + list(errado)))
        return f"{n[:3]}.{n[3:6]}.{n[6:9]}-{n[9:]}"


def _nome(rng: random.Random, sexo: str, usados: set[str], sobrenome: str | None = None) -> str:
    while True:
        primeiro = rng.choice(PRIMEIROS_F if sexo == "F" else PRIMEIROS_M)
        nome = f"{primeiro} {rng.choice(SOBRENOMES)} {sobrenome or rng.choice(SOBRENOMES)}"
        if nome not in usados:
            usados.add(nome)
            return nome


def _data(ano: int, mes: int, dia: int) -> str:
    return f"{dia:02d}/{mes:02d}/{ano}"


def gerar_turmas_e_alunos(ano: int, rng: random.Random) -> tuple[dict, list[dict], list[dict]]:
    """(turmas.json, alunos.json, responsáveis para a pré-matrícula)."""
    usados: set[str] = set()
    turmas, alunos = {}, []
    seq = 0
    for nome_turma, idade, quantidade in TURMAS_MODELO:
        lista = []
        for n in range(1, quantidade + 1):
            seq += 1
            sexo = rng.choice(["F", "M"])
            sobrenome_familia = rng.choice(SOBRENOMES)
            nome = _nome(rng, sexo, usados, sobrenome_familia)
            cgm = f"9{str(ano)[-2:]}{seq:07d}"
            nasc = _data(ano - idade, rng.randint(1, 12), rng.randint(1, 28))
            situacao = "Transferido" if (seq % 17 == 0) else "Matriculado"
            lista.append({"N": n, "CGM": cgm, "Nome": nome, "Data Nasc.": nasc, "Idade": idade, "Sexo": sexo,
                          "Situação": situacao, "Data Matricula": _data(ano, 2, rng.randint(1, 10))})
            mae = _nome(rng, "F", usados, sobrenome_familia)
            pai = _nome(rng, "M", usados, sobrenome_familia)
            alunos.append({
                "Nome": nome, "CGM": cgm, "Data Nascimento": nasc,
                "Sexo": "Feminino" if sexo == "F" else "Masculino", "Estado Civil": "Solteiro(a)",
                "Município Nascimento": "PONTA GROSSA", "UF Nascimento": "PR", "Nacionalidade": "Brasileira",
                "Cor": rng.choice(["Branca", "Parda", "Preta", "Amarela"]),
                "RG": f"{rng.randint(10, 99)}.{rng.randint(100, 999)}.{rng.randint(100, 999)}-{rng.randint(0, 9)}",
                "Data Expedição RG": _data(ano - 1, 3, 15), "Órgão Emissor": "SESP", "UF RG": "PR",
                "CPF": _cpf_ficticio(rng), "Mãe": mae, "Pai": pai, "Responsável": mae, "Parentesco": "Mãe",
                "CPF Responsável": _cpf_ficticio(rng),
                "CEP": "84000-000", "UF": "PR", "Cidade": "PONTA GROSSA", "Endereço": f"RUA EXEMPLO {seq}",
                "Número": str(100 + seq), "Complemento": "", "Bairro": "BAIRRO TESTE",
                "Celular Aluno": "", "Celular Responsável": f"(00) 00000-{seq:04d}", "Telefone Residencial": "",
                "Telefone Comercial": "", "Email Aluno": "",
                "Email Responsável": f"responsavel{seq}@example.com", "Email Google": "",
                "Bolsa Família": rng.choice(["Sim", "Não", "Não"]), "NIS Estudante": "", "NIS Responsável": "",
            })
        turmas[nome_turma] = lista
    return turmas, alunos, usados


def gerar_funcionarios(ano: int, rng: random.Random, usados: set[str], nome_escola: str) -> tuple[list, list, list]:
    """(funcionarios.json, funcionarios_completo.json, funcionarios_matriculas.json)."""
    basico, completo, vinculos = [], [], []
    for i, (funcao, curso, vinculo) in enumerate(FUNCIONARIOS_MODELO, 1):
        sexo = rng.choice(["F", "F", "M"])
        nome = _nome(rng, sexo, usados)
        cpf = _cpf_ficticio(rng)
        turmas = []
        if funcao == "Docente":
            t = rng.choice(TURMAS_MODELO)[0]
            turmas = [{"descricao": f"- {t} - Ensino Fundamental", "disciplinas": ["Língua Portuguesa", "Matemática"]}]
        reg = {"nome": nome, "cpf": cpf, "funcao": funcao, "rg": f"{rng.randint(10, 99)}.{rng.randint(100, 999)}.{rng.randint(100, 999)}-{rng.randint(0, 9)}",
               "nome_mae": _nome(rng, "F", usados), "email": f"funcionario{i}@example.com",
               "curso_superior": curso, "pos_graduacao": [], "turmas": turmas}
        basico.append(reg)
        completo.append({
            "cpf": cpf, "data_consulta": f"{ano}-03-01 10:00:00", "nome_completo": nome,
            "data_nascimento": _data(ano - rng.randint(25, 55), rng.randint(1, 12), rng.randint(1, 28)),
            "email": reg["email"], "telefone": f"(00) 00000-{i:04d}", "nome_mae": reg["nome_mae"],
            "municipio_nascimento": "PONTA GROSSA", "uf_nascimento": "PR", "cep": "84000-000", "municipio_endereco": "PONTA GROSSA",
            "uf_endereco": "PR", "endereco": f"RUA TESTE {i}", "bairro": "BAIRRO TESTE", "numero": str(10 + i),
            "rg": reg["rg"], "uf_rg": "PR", "orgao_emissor_rg": "SESP",
            "raca_cor": rng.choice(["Branca", "Parda"]), "escolaridade": "Superior" if curso else "Médio",
            "sexo": sexo, "zona_residencial": "Urbana",
        })
        base = {"cpf": cpf, "nome": nome, "funcao": funcao, "nome_curto_risco_homonimo": False, "dados_originais": reg,
                "revisar": [], "ajuste_manual": False, "estagiario_encontrado": None}
        if vinculo in ("servidor", "servidor_fora"):
            numcad = str(900000 + i)
            local = nome_escola.upper() if vinculo == "servidor" else "SEDE SME"
            v = {"numcad": numcad, "numemp": 1, "nomemp": "PREFEITURA MUNICIPAL DE PONTA GROSSA (FICTÍCIO)",
                 "nomloc": "PMPG-SME-FUNDEB 40%-Ens.Fundamental", "titcar": funcao.upper(), "datadm": f"01/02/{ano - 5}",
                 "dessit": "Trabalhando", "forma_ingresso": "Concurso", "match_score": 100.0, "match_tipo": "exato",
                 "match_nome_api": nome}
            vinculos.append({**base, "matricula_encontrada": True, **v, "origem_vinculo": "servidores", "vinculo": "servidor",
                             "terceirizado": False, "terceirizado_origem": None, "vinculos_servidores": [v],
                             "multiplas_matriculas": False, "na_escola": vinculo == "servidor", "comprovacao": "holerite",
                             "local_trabalho_holerite": local, "holerite_mes": f"09-{ano}",
                             "revisar": [] if vinculo == "servidor" else [f"o holerite aponta outro local de trabalho: {local} (pode ser homônimo)"]})
        elif vinculo == "terceirizado":
            vinculos.append({**base, "matricula_encontrada": False, **{c: None for c in ("numcad", "numemp", "nomemp", "nomloc", "titcar", "datadm", "dessit", "forma_ingresso", "match_score", "match_nome_api")},
                             "match_tipo": "nenhum", "origem_vinculo": None, "vinculos_servidores": [], "multiplas_matriculas": False,
                             "vinculo": "terceirizado", "terceirizado": True, "terceirizado_origem": "nao_consta_no_rh",
                             "na_escola": True, "comprovacao": "sere", "local_trabalho_holerite": None, "holerite_mes": None,
                             "revisar": ["não consta no RH: marcado como terceirizado por inferência"]})
        else:                                                   # estagiário
            vinculos.append({**base, "matricula_encontrada": False, **{c: None for c in ("numcad", "numemp", "nomemp", "nomloc", "titcar", "datadm", "dessit", "forma_ingresso", "match_score", "match_nome_api")},
                             "match_tipo": "nenhum", "origem_vinculo": "estagiarios", "vinculos_servidores": [], "multiplas_matriculas": False,
                             "vinculo": "estagiario", "terceirizado": False, "terceirizado_origem": None,
                             "na_escola": True, "comprovacao": "sere", "local_trabalho_holerite": None, "holerite_mes": None})
    return basico, completo, vinculos


def gerar_pre_matricula(ano: int, rng: random.Random, usados: set[str], nome_escola: str) -> dict:
    """pre_matricula.json no formato real (turmas_intencao + cadastros), com matriculados, aguardando e cancelados."""
    intencao: dict[str, list] = {}
    cadastros: dict[str, dict] = {}
    destinos = [("Infantil IV", 3), ("Infantil V", 3), ("1º Ano do Ensino Fundamental", 5), ("2º Ano do Ensino Fundamental", 3)]
    situacoes = ["Matriculado", "Matriculado", "", "", "Cancelado. Motivo: Responsável desistiu da vaga"]
    seq = 0
    for turma, quantidade in destinos:
        lista = []
        for pos in range(1, quantidade + 1):
            seq += 1
            sexo = rng.choice(["F", "M"])
            sobrenome = rng.choice(SOBRENOMES)
            aluno = _nome(rng, sexo, usados, sobrenome)
            responsavel = _nome(rng, "F", usados, sobrenome)
            cpf = _cpf_ficticio(rng)
            situacao = situacoes[seq % len(situacoes)]
            lista.append({"pos": pos, "nome": aluno, "cpf": cpf, "tipo": "Normal", "pontuacao": str(rng.randint(10, 90)),
                          "tr_id": f"{ano}{seq:05d}", "situacao": situacao, "presente_na_ultima_coleta": True})
            cadastros[cpf] = {
                "cpf": cpf, "tr_id": f"{ano}{seq:05d}", "nome_aluno": aluno, "nome_responsavel": responsavel,
                "telefone": f"(00) 00000-{seq:04d}", "email": f"pais{seq}@example.com", "endereco": f"RUA EXEMPLO {seq}",
                "escolas_escolhidas": {"turma": turma, "opcoes": [
                    {"escola": nome_escola, "situacao": situacao or None,
                     **({"motivo_cancelamento": "Responsável desistiu da vaga"} if situacao.startswith("Cancelado") else {})}]},
            }
        intencao[turma] = lista
    return {"atualizado_em": f"{ano}-01-20T09:00:00", "turmas_intencao": intencao, "cadastros": cadastros}


# ───────────────────────────── ponto de entrada ─────────────────────────────

def _escola() -> str:
    try:
        from src.comum import escola
        return escola.nome() or "Escola Municipal Teste"
    except Exception:                                           # noqa: BLE001 — a escola não configurada não impede o teste
        return "Escola Municipal Teste"


def pasta_tem_dados_reais(pasta: Path) -> bool:
    """True se a pasta tem arquivos e NÃO é uma pasta de dados fictícios (sem a marca)."""
    if not pasta.is_dir():
        return False
    arquivos = [p for p in pasta.rglob("*") if p.is_file()]
    return bool(arquivos) and not (pasta / MARCADOR).exists()


def pasta_e_ficticia(pasta: Path) -> bool:
    return (pasta / MARCADOR).exists()


def gerar_dados_ficticios(ano, com_backup: bool = False) -> dict:
    """
    Cria os arquivos fictícios em dados/<ano>/. ValueError (mensagem pronta) se o ano for inválido ou se a pasta
    já tiver dados reais. Devolve o resumo {"ano","pasta","arquivos","turmas","alunos","funcionarios","pre_matricula","backup"}.
    """
    from src.comum.configuracao import validar_ano_letivo
    ano_txt = validar_ano_letivo(ano)
    pasta = paths.DADOS_DIR / ano_txt
    if pasta_tem_dados_reais(pasta):
        raise ValueError(f"A pasta dados/{ano_txt} já tem dados (que não são fictícios). Por segurança nada foi escrito: "
                         "use outro ano ou apague/mova essa pasta antes.")
    rng = random.Random(f"{SEMENTE}-{ano_txt}")
    nome_escola = _escola()
    turmas, alunos, usados = gerar_turmas_e_alunos(int(ano_txt), rng)
    basico, completo, vinculos = gerar_funcionarios(int(ano_txt), rng, usados, nome_escola)
    pre = gerar_pre_matricula(int(ano_txt), rng, usados, nome_escola)

    pasta.mkdir(parents=True, exist_ok=True)
    arquivos = {"turmas.json": turmas, "alunos.json": alunos, "funcionarios.json": basico,
                "funcionarios_completo.json": completo, "funcionarios_matriculas.json": vinculos, "pre_matricula.json": pre}
    for nome, dados in arquivos.items():
        (pasta / nome).write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    (pasta / MARCADOR).write_text(
        f"DADOS FICTÍCIOS do ano letivo {ano_txt}, gerados em {date.today():%d/%m/%Y} por src/comum/dados_ficticios.py "
        "para testes.\nNomes, CPFs (dígitos verificadores errados), telefones e e-mails (@example.com) são inventados.\n"
        "Pode apagar esta pasta sem perder nada de verdade.\n", encoding="utf-8")

    backup_nome = None
    if com_backup:
        from src.comum import backup
        backup_nome = backup.criar_backup(motivo="dados_ficticios", ano=ano_txt).name
    return {"ano": ano_txt, "pasta": str(pasta), "arquivos": sorted(arquivos) + [MARCADOR],
            "turmas": len(turmas), "alunos": len(alunos), "funcionarios": len(basico),
            "pre_matricula": sum(len(v) for v in pre["turmas_intencao"].values()), "backup": backup_nome}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gera dados fictícios de um ano letivo (para testes)")
    ap.add_argument("--ano", required=True, help="ano letivo, ex.: 2025")
    ap.add_argument("--backup", action="store_true", help="cria também um backup desse ano (para testar a restauração)")
    args = ap.parse_args(argv)
    try:
        r = gerar_dados_ficticios(args.ano, com_backup=args.backup)
    except ValueError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    print(f"Dados fictícios de {r['ano']} criados em {r['pasta']}: {r['turmas']} turmas, {r['alunos']} alunos, "
          f"{r['funcionarios']} funcionários, {r['pre_matricula']} na pré-matrícula." + (f" Backup: {r['backup']}" if r["backup"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
